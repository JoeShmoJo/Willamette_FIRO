# -*- coding: utf-8 -*-
"""
Created on Fri Oct  9 13:38:39 2026

@author: g2echsfb
"""

import pandas as pd 
import numpy as np
import pickle
from scipy.stats import skew, pearson3


### config
CONFIG = r'../config/space_limits_config.xlsx'
STOR_ELEV = r"../data/storage_elevation.xlsx"
DATA_DICT = r"../out/available_volume.pkl"
LAG_TIMES = r"../data/ResvLagTimes_Median.csv"
PERCENT_CHANCE_EXCEEDED = 90

CONTROL_POINT_SPACE =r'../out/ControlPointsSpace.csv'
RESERVOIR_EVAC_LIMITS = r'../out/ReservoirEvacLimits.csv'
LIMITING_FACTORS = r'../out/ReservoirLimitingFactors.csv'
### Funtions
def fit_distribution(event_volumes):
    results = {}
    for cp, df in event_volumes.items():
        data = pd.to_numeric(df['available_volume_kaf'], errors='coerce').to_numpy(dtype=float)
        data = data[np.isfinite(data)]
        
        mean_val = np.mean(data)
        std_val = np.std(data, ddof=1)
        skew_val = skew(data, bias=False)

        dist = pearson3(skew=skew_val, loc=mean_val, scale=std_val)

        percent_exceeded = np.arange(1, 100)
        non_exceedance = 1 - percent_exceeded / 100
        median_curve = dist.ppf(non_exceedance)

        results[cp] = pd.DataFrame({'median_curve': median_curve}, index=pd.Index(percent_exceeded, name='percent_exceeded'))
    return results

def find_conservation_storage(project_data, stor_elev):
    '''
    Calculate conservation storage for each project using its minimum and
    maximum conservation elevations and the corresponding storage-elevation
    rating curve. The combined Lookout Point + Hills Creek project is
    assigned the sum of their individual conservation storages.
    '''
    project_data = project_data.copy()
    conservation_storage = {}
    # Calculate conservation storage for each individual project
    for row in project_data.itertuples(index=False):
        project = row.Reservoir
        # Skip the combined project for now
        if project == "Lookout Point+Hills Creek":
            continue
        max_con = row.MaxCon
        min_con = row.MinCon
        # Filter and sort rating curve for this project
        stor_elev_project = stor_elev[stor_elev['Project'] == project].sort_values('Elevation (ft)')
        if stor_elev_project.empty:
            print(f'No rating curve found for {project}')
            conservation_storage[project] = np.nan
            continue
        elevations = stor_elev_project['Elevation (ft)'].to_numpy()
        storages = stor_elev_project['Storage (ac-ft)'].to_numpy()

        # Interpolate storage at conservation elevations
        max_storage = np.interp(max_con, elevations, storages)
        min_storage = np.interp(min_con, elevations, storages)

        # Conservation storage in KAF
        conservation_storage[project] = (max_storage - min_storage ) / 1000

    # Calculate combined conservation storage
    combined_project = "Lookout Point+Hills Creek"
    if combined_project in project_data['Reservoir'].values:
        lookout_storage = conservation_storage.get("Lookout Point", np.nan)
        hills_storage = conservation_storage.get("Hills Creek", np.nan)
        conservation_storage[combined_project] = (lookout_storage + hills_storage)
    # Map results back to the original DataFrame
    project_data['ConStorageKAF'] = project_data['Reservoir'].map(conservation_storage)
    return project_data

def calculate_7_day_evacuation_volume(project_data):
    '''
    Calculate the seven-day evacuation volume for each project based on its
    conservation storage and specified evacuation period.

    Parameters
    ----------
    project_data : pandas.DataFrame
        DataFrame containing project-level storage and evacuation information.
        Must include the following columns:
        - 'ConStorageKAF': Project conservation storage (KAF)
        - 'DaysToEvac20Percent': Number of days to evacuate 20% of conservation 
        storage

    Returns
    -------
    pandas.DataFrame
        A copy of `project_data` with an additional column:
        - 'SevenDayEvacuationVolumeKAF': Estimated volume that can be
          evacuated over seven days (KAF)
    '''
    project_data = project_data.copy()
    seven_day_evacuation_volumes = []
    for row in project_data.itertuples():
        conservation_storage_kaf = row.ConStorageKAF
        target_evacuation_volume_kaf = conservation_storage_kaf * 0.20
        days_to_evacuate = row.DaysToEvac20Percent
        daily_evacuation_rate_kaf = (target_evacuation_volume_kaf / days_to_evacuate)
        seven_day_evacuation_volume_kaf = (7 * daily_evacuation_rate_kaf)
        seven_day_evacuation_volumes.append(seven_day_evacuation_volume_kaf)
    project_data["SevenDayEvacuationVolumeKAF"] = (seven_day_evacuation_volumes)
    return project_data

def distribute_downstream_space(project_data, alternatives, control_point_space):  
    '''
    For each alternative, projects are mapped to their corresponding downstream
    control points. The total upstream conservation storage is calculated for
    each control point, and the available downstream FIRO space is allocated 
    to individual projects in proportion to their conservation storage.

    Parameters
    ----------
    project_data : pandas.DataFrame
        DataFrame containing project information, including the project
        identifier ('Project') and conservation storage ('ConStorageKAF').

    alternatives : pandas.DataFrame
        DataFrame defining the project-to-control-point assignments for each
        alternative. Each column represents an alternative

    control_point_space : pandas.DataFrame
        Dataframe of downstream locations and amount of available space.

    Returns
    -------
    dict
        Dictionary containing the results for each alternative
    '''
    project_data = project_data.copy()
    results = {}
    for col in alternatives.columns:
        control_point_dict = alternatives[col].to_dict()
        # add control point to project_data 
        project_data['ControlPoint'] = project_data['Reservoir'].map(control_point_dict)
        alternative = project_data.dropna(subset=["ControlPoint"])
        alternative = alternative.copy() # create a copy
        # find the total upstream storage for each regulating control point
        total_us_con_storage = alternative.groupby("ControlPoint")["ConStorageKAF"].sum()
        ds_space = []
        stor_percent = []
        for row in alternative.itertuples():
            # find the project's con storage, the downstream control point, and total storage available for that control point
            con_stor = row.ConStorageKAF
            ds_control_point = row.ControlPoint
            # total storage at indiviual projects
            total_stor = total_us_con_storage.loc[ds_control_point]
            # Available FIRO space for that control point 
            total_available_ds_space = control_point_space["SpaceLimit"].loc[ds_control_point]
            # find the percent of storage allocated for that project 
            percent = con_stor / total_stor
            project_space = percent * total_available_ds_space
            stor_percent.append(percent)
            ds_space.append(project_space)
        alternative["StorPercent"] = stor_percent
        alternative["DownstreamSpaceKAF"] = ds_space
        results[col] = alternative
    return results

def caclulate_lag_times(lag_times):
    lag_times = lag_times.copy()
    lag_times = lag_times.set_index("Reservoir")
    results = []
    for col in lag_times.columns:
        if col == "ConStorageKAF":
            continue
        df = lag_times[[col, "ConStorageKAF"]].dropna(subset=[col])
        # Skip empty columns or columns with zero total weight
        if df.empty or df["ConStorageKAF"].sum() == 0:
            continue
        results.append({"Reservoir": col, "WeightedLagTime": np.average(df[col], weights=df["ConStorageKAF"]),
            "MeanLagTime": df[col].mean(), "MaxLagTime": df[col].max(), "MinLagTime": df[col].min()})
    return pd.DataFrame(results)

def space_limits_at_control_points(fitted_data, project_data, CONTROL_POINT_SPACE, PERCENT_CHANCE_EXCEEDED):
    rows = []
    for key, df in fitted_data.items():
        space_limit = df["median_curve"].loc[PERCENT_CHANCE_EXCEEDED]
        rows.append((key, space_limit))
    control_points_space_limits = pd.DataFrame(rows, columns=["ControlPoint", "SpaceLimit"])
    return control_points_space_limits.set_index('ControlPoint')
 

def summary_of_alternatives(alternative_dict, project_data):
    """
    Create limiting-factor summary tables for all available factors.

    Returns:
        percent_df: Limiting factors and percent of conservation storage.
        space_df: Limiting factors and downstream-space KAF. "Normal Evac"
            uses SevenDayEvacuationVolumeKAF as its KAF value.

    Special case:
        Lookout Point+Hills Creek is treated as a series combination:
        - ConStorageKAF = Lookout Point storage + Hills Creek storage.
        - Control-point percentages match Lookout Point.
        - Control-point KAF values are scaled to combined storage.
        - Normal Evac uses the combined row's own evacuation-volume value.
    """
    series_combinations = {
        "Lookout Point+Hills Creek": {
            "storage_components": ["Lookout Point", "Hills Creek"],
            "control_point_percent_source": "Lookout Point"}}
    base_cols = ["Reservoir", "ConStorageKAF", "SevenDayEvacuationVolumeKAF"]
    base_df = project_data[base_cols].drop_duplicates(subset="Reservoir").copy().set_index("Reservoir")
    for combined_reservoir, config in series_combinations.items():
        storage_components = config["storage_components"]
        missing_components = [reservoir for reservoir in storage_components if reservoir not in base_df.index]
        if missing_components:
            raise ValueError(f"Missing storage-component reservoir(s) for '{combined_reservoir}': {missing_components}")
        if combined_reservoir not in base_df.index:
            raise ValueError(f"'{combined_reservoir}' must exist in project_data so its SevenDayEvacuationVolumeKAF can be used for Normal Evac.")
        base_df.loc[combined_reservoir, "ConStorageKAF"] = base_df.loc[storage_components, "ConStorageKAF"].sum()
    base_df = base_df.reset_index()
    normal_evac_df = base_df[["Reservoir", "ConStorageKAF", "SevenDayEvacuationVolumeKAF"]].copy()
    normal_evac_df["Limiting Factor"] = "Normal Evac"
    normal_evac_df["SpaceKAF"] = normal_evac_df["SevenDayEvacuationVolumeKAF"]
    normal_evac_df["Percent"] = normal_evac_df["SpaceKAF"] / normal_evac_df["ConStorageKAF"] * 100
    factor_list = [normal_evac_df[["Reservoir", "Limiting Factor", "SpaceKAF", "Percent"]]]
    storage_map = base_df.set_index("Reservoir")["ConStorageKAF"].to_dict()
    for control_point, df in alternative_dict.items():
        if control_point == "NearestDSControlPoint":
            continue
        control_df = df[["Reservoir", "DownstreamSpaceKAF"]].copy()
        for combined_reservoir, config in series_combinations.items():
            source_reservoir = config["control_point_percent_source"]
            source_rows = control_df[control_df["Reservoir"] == source_reservoir].copy()
            control_df = control_df[control_df["Reservoir"] != combined_reservoir]
            if source_rows.empty:
                continue
            source_storage = storage_map.get(source_reservoir)
            combined_storage = storage_map.get(combined_reservoir)
            if pd.isna(source_storage) or pd.isna(combined_storage):
                continue
            source_rows["DownstreamSpaceKAF"] = source_rows["DownstreamSpaceKAF"] / source_storage * combined_storage
            source_rows["Reservoir"] = combined_reservoir
            control_df = pd.concat([control_df, source_rows], ignore_index=True)
        control_df = control_df.merge(base_df[["Reservoir", "ConStorageKAF"]], on="Reservoir", how="left")
        control_df["Limiting Factor"] = control_point
        control_df["SpaceKAF"] = control_df["DownstreamSpaceKAF"]
        control_df["Percent"] = control_df["SpaceKAF"] / control_df["ConStorageKAF"] * 100
        factor_list.append(control_df[["Reservoir", "Limiting Factor", "SpaceKAF", "Percent"]])
    factors_df = pd.concat(factor_list, ignore_index=True).dropna(subset=["Reservoir", "SpaceKAF", "Percent"])
    factors_df = factors_df.sort_values(["Reservoir", "Limiting Factor", "SpaceKAF"]).groupby(["Reservoir", "Limiting Factor"], as_index=False).first()
    factors_df = factors_df.sort_values(["Reservoir", "Percent", "Limiting Factor"])
    factors_df["FactorNumber"] = factors_df.groupby("Reservoir").cumcount() + 1
    num_factors = int(factors_df["FactorNumber"].max()) if not factors_df.empty else 0
    factor_name_pivot = factors_df.pivot(index="Reservoir", columns="FactorNumber", values="Limiting Factor")
    percent_pivot = factors_df.pivot(index="Reservoir", columns="FactorNumber", values="Percent")
    space_pivot = factors_df.pivot(index="Reservoir", columns="FactorNumber", values="SpaceKAF")
    percent_df = base_df[["Reservoir"]].set_index("Reservoir")
    space_df = base_df[["Reservoir"]].set_index("Reservoir")
    for i in range(1, num_factors + 1):
        percent_df[f"Limiting Factor {i}"] = factor_name_pivot[i] if i in factor_name_pivot.columns else pd.NA
        percent_df[f"Percent {i}"] = percent_pivot[i] if i in percent_pivot.columns else pd.NA
        space_df[f"Limiting Factor {i}"] = factor_name_pivot[i] if i in factor_name_pivot.columns else pd.NA
        space_df[f"DownstreamSpaceKAF {i}"] = space_pivot[i] if i in space_pivot.columns else pd.NA
    percent_df = percent_df.reset_index()
    space_df = space_df.reset_index()
    for i in range(1, num_factors + 1):
        percent_df[f"Percent {i}"] = percent_df[f"Percent {i}"].map(lambda x: f"{x:.1f}%" if pd.notna(x) else "")
        space_df[f"DownstreamSpaceKAF {i}"] = space_df[f"DownstreamSpaceKAF {i}"].map(lambda x: f"{x:.1f}" if pd.notna(x) else "")
    return percent_df, space_df


######### Code starts 
if __name__ == "main" or __name__ == "__main__":
    
    with open(DATA_DICT, 'rb') as file:
        data_dict = pickle.load(file)
    
    # Bring in data
    stor_elev = pd.read_excel(STOR_ELEV)
    # cp_data = pd.read_excel(CONFIG, sheet_name="control_points", skiprows=5)
    alternatives = pd.read_excel(CONFIG, sheet_name="alternatives", skiprows=5).set_index('Project')
    # Find lag times
    lag_times = pd.read_csv(LAG_TIMES)
    lag_times_df = caclulate_lag_times(lag_times)

    # fit the data to a Person III distribution 
    fitted_data = fit_distribution(data_dict)
    
    # Find conservation storage and the volume that can be evacualted in seven days
    project_data = pd.read_excel(CONFIG, sheet_name="reservoirs", skiprows=5)
    project_data = find_conservation_storage(project_data, stor_elev)
    project_data = calculate_7_day_evacuation_volume(project_data)
    
    # output evac rates: 
    evac_rates = project_data[['Reservoir','DaysToEvac20Percent','SevenDayEvacuationVolumeKAF']]
    evac_rates.to_csv(RESERVOIR_EVAC_LIMITS, index=False)
    
    # Find available space at each control point 
    control_point_space = space_limits_at_control_points(fitted_data, project_data, CONTROL_POINT_SPACE, PERCENT_CHANCE_EXCEEDED)
    control_point_space.to_csv(CONTROL_POINT_SPACE)
    
    # divide the available space at each control point among the upsteam reservoirs 
    alterative_dict = distribute_downstream_space(project_data, alternatives, control_point_space)
    
    # Find and output a table of the limiting factors 
    percent_df, space_df = summary_of_alternatives(alterative_dict, project_data)
    percent_df.to_csv(LIMITING_FACTORS, index=False) 
    
 

