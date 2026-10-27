# -*- coding: utf-8 -*-
"""
Created on Fri Oct  9 13:38:39 2026

@author: g2echsfb
"""

import pandas as pd 
import requests
import numpy as np
import pickle
from scipy.interpolate import interp1d
import numpy as np
from scipy.stats import skew, pearson3
import matplotlib.pyplot as plt
from pydsstools.heclib.dss import HecDss
from pydsstools.core import TimeSeriesContainer
import matplotlib.dates as mdates

### config
CONFIG = r'../config/config.xlsx'
STOR_ELEV = r"../data/storage_elevation.xlsx"
DATA_DICT = r"../output/available_volume.pkl"
CONTROL_POINT_SPACE =r'../output/control_points_space.csv'
PROJECT_DATA  = r'../output/project_data.csv'
PERCENT_CHANCE_EXCEEDED = 90

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
        project = row.Project
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
    if combined_project in project_data['Project'].values:
        lookout_storage = conservation_storage.get("Lookout Point", np.nan)
        hills_storage = conservation_storage.get("Hills Creek", np.nan)
        conservation_storage[combined_project] = (lookout_storage + hills_storage)
    # Map results back to the original DataFrame
    project_data['ConStorageKAF'] = project_data['Project'].map(conservation_storage)
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
        - 'DaysToEvac': Number of days to evacuate 20% of conservation 
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
        days_to_evacuate = row.DaysToEvac
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
        project_data['ControlPoint'] = project_data['Project'].map(control_point_dict)
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

def calculate_limiting_space(alternative_dict, project_data, HCR_LOP_COMBINED_EVAC_RATE=True):
    '''
    if frio space > max evac space, it will use evac space.
    Caviout 
    '''
    HCR_LOP_evac_rate_combined = project_data.loc[project_data["Project"] == "Lookout Point+Hills Creek", "SevenDayEvacuationVolumeKAF"].iloc[0]
    for alt, df in alternative_dict.items(): 
        df = df.copy()
        firo_space_kaf = []
        limiting_factors = []
        for row in df.itertuples():
            if HCR_LOP_COMBINED_EVAC_RATE:
                if row.Project == "Hills Creek" or row.Project == "Lookout Point":
                    seven_day_evacuation_kaf = HCR_LOP_evac_rate_combined
                else: 
                    seven_day_evacuation_kaf = row.SevenDayEvacuationVolumeKAF
            else:
                seven_day_evacuation_kaf = row.SevenDayEvacuationVolumeKAF
            downstream_space_kaf = row.DownstreamSpaceKAF
            if seven_day_evacuation_kaf < downstream_space_kaf:
                firo_space = seven_day_evacuation_kaf
                limiting_factor = "Evacuation Rate"
            elif downstream_space_kaf < seven_day_evacuation_kaf:
                firo_space = downstream_space_kaf
                limiting_factor = "Downstream Space"
            else:
                firo_space = seven_day_evacuation_kaf
                limiting_factor = "Both"
            firo_space_kaf.append(firo_space)
            limiting_factors.append(limiting_factor)
        df["FIROSpaceKAF"] = firo_space_kaf
        df["LimitingFactor"] = limiting_factors
        alternative_dict[alt] = df

def summary_of_alternatives(alterative_dict, project_data):
    # TODO, turn this into table for public communication
    """
    Create one DataFrame with summary information for each alternative.
    """
    # Start with project-level data
    summary_df = pd.DataFrame({
        "Project": project_data["Project"], "ConStorageKAF": project_data["ConStorageKAF"],
        "SevenDayEvacuationVolumeKAF": project_data["SevenDayEvacuationVolumeKAF"]})

    # Add downstream space for each alternative
    for alt, df in alterative_dict.items():
        project_space_map = dict(zip(df["Project"], df["DownstreamSpaceKAF"]))
        summary_df[f"{alt}"] = (summary_df["Project"].map(project_space_map))
    summary_df = summary_df.set_index('Project')
    for col in summary_df.columns:
        if col == "ConStorageKAF":
            continue
        else:
            summary_df[f'{col}_percent'] = summary_df[col] / summary_df["ConStorageKAF"]
    summary_df.to_csv(r'../output/project_space_summary.csv')

def caclulate_lag_times(lag_times):
    lag_times = lag_times.copy()
    # Don't include Hills Creek
    # lag_times = lag_times[lag_times["Reservoir"] != "Hills Creek"]
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

def limits_at_locations(fitted_data, project_data, CONTROL_POINT_SPACE, PERCENT_CHANCE_EXCEEDED):
    rows = []
    for key, df in fitted_data.items():
        space_limit = df["median_curve"].iloc[PERCENT_CHANCE_EXCEEDED]
        rows.append((key, space_limit))

    control_points_space_limits = pd.DataFrame(rows, columns=["Location", "SpaceLimit"])
    # write to csv 
    # control_points_space_limits.to_csv(CONTROL_POINT_SPACE, index=False)

    return control_points_space_limits.set_index('Location')
 

######### Code starts 
if __name__ == "main" or __name__ == "__main__":
    
    with open(DATA_DICT, 'rb') as file:
        data_dict = pickle.load(file)
    
    # Bring in data
    cp_data = pd.read_excel(CONFIG, sheet_name="control_points", skiprows=5)
    alternatives = pd.read_excel(CONFIG, sheet_name="alternatives", skiprows=5).set_index('Project')
    # weigth lag time based on conservation storage:
    lag_times = pd.read_csv("../data/ResvLagTimes_Median.csv")
    lag_times_df = caclulate_lag_times(lag_times)
    # storage elevtion
    pd.read_excel(STOR_ELEV)
    stor_elev = pd.read_excel(STOR_ELEV)
    
    # fit the data to a Person III distribution 
    fitted_data = fit_distribution(data_dict)
    
    # Find FIRO space at each project for each alterative  
    stor_elev = pd.read_excel(STOR_ELEV)
    project_data = pd.read_excel(CONFIG, sheet_name="projects", skiprows=5)
    project_data = find_conservation_storage(project_data, stor_elev)
    project_data = calculate_7_day_evacuation_volume(project_data)
    # project_data.to_csv(PROJECT_DATA, index=False)
    
    # distribute_downstream_space(project_data, alternatives, control_point_space)
    control_point_space = limits_at_locations(fitted_data, project_data, CONTROL_POINT_SPACE, PERCENT_CHANCE_EXCEEDED)
    # alterative_dict = distribute_downstream_space(project_data, alternatives, control_point_space)
    # calculate_limiting_space(alterative_dict, project_data, HCR_LOP_COMBINED_EVAC_RATE=True)
    # summary_of_alternatives(alterative_dict, project_data)
    ##################

    
 

