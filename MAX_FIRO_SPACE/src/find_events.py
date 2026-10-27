# -*- coding: utf-8 -*-
"""
Created on Thu Oct 15 16:43:58 2026

@author: g2echsfb
"""

import pandas as pd 
import requests
import numpy as np
import pickle
from scipy.interpolate import interp1d
import matplotlib.pyplot as plt
from pydsstools.heclib.dss import HecDss
from pydsstools.core import TimeSeriesContainer
import matplotlib.dates as mdates

### config
CONFIG = r'../config/space_limits_config.xlsx'

FLOW_DATA = r"../data/OutputLocalUnreg.dss"
FLOW_PICKLE = r'../data/localUnreg.pkl'

BANKFULL_CSV = r'../out/BankfullValues.csv'
DSS_OUT = r"../out/spaceComponents.dss"
EVENT_VOLUME_PICKLE = r"../out/EventVolume.pkl"
REDOWNLOAD_DATA = False
######### Funtions 
def cfs_to_kaf(cfs, timestep_hr=1):
    cf = cfs * 3600 * timestep_hr
    kaf = cf / 43560 / 1000
    return kaf

def read_all_pathnames(dss_file, sort_paths=True):
    """
    Read all DSS pathnames, remove the D part, and return unique pathnames.

    Example:
        /A/B/C/01JAN2025/1HOUR/F/
    becomes:
        /A/B/C//1HOUR/F/
    """
    with HecDss.Open(str(dss_file)) as dss:
        all_pathnames = dss.search_path(sort=sort_paths)
    unique_pathnames = set()
    for path in all_pathnames:
        parts = path.split("/")
        # DSS pathname layout after splitting:
        # ['', A, B, C, D, E, F, '']
        if len(parts) >= 8:
            parts[4] = ""  # Remove the D part.
            unique_pathnames.add("/".join(parts))
    return sorted(unique_pathnames)

def read_DSS_data(DSS_file, pathname, time_window=False, start_time=None, end_time=None, drop_missing=False):
    """
    Returns a DataFrame with index as the TimeStamp, and column as the data
    """
    pathname = pathname.upper()
    if pd.isna(pathname) or pathname == "": #not defined, skip it
        raise Exception("Read failed: {pathname}")
    if time_window: 
        with HecDss.Open(DSS_file) as fid:
            ts = fid.read_ts(pathname, window=(start_time, end_time), trim_missing=drop_missing)
    else: 
        with HecDss.Open(DSS_file) as fid:
            ts = fid.read_ts(pathname, trim_missing=drop_missing)
    if ts is None or ts.values is None:  # or (-901 in ts.values and "IR-CENTURY" in pathname): 
        print("Read failed: {pathname}") 
        return pd.DataFrame()
    dt_index = [t.datetime() for t in ts.times]
    df_out = pd.DataFrame(index=pd.to_datetime(dt_index))
    # df_out = pd.DataFrame(index = ts.times) # updated by Sam 
    
    df_out.index.name = 'DateTime'
    df_out["value"] = ts.values
    if drop_missing:
        df_out = df_out[df_out.value != -901] #drop the missing values
        df_out = df_out[df_out.value != -902] #drop the missing values
        df_out = df_out.dropna()
    else:
        df_out = df_out.replace(-901, np.nan)
        df_out = df_out.replace(-902, np.nan)
    return df_out    

def load_data_dict(DSS_file): 
    data_dict = {}
    pathnames = read_all_pathnames(DSS_file)
    
    for path in pathnames: 
        b_part = path.split("/")[2]
        df = read_DSS_data(DSS_file, pathname=path)
        data_dict[b_part] = df
    return data_dict

def get_rating_table(site, onlyTenths=True):
    url = f"https://api.water.noaa.gov/nwps/v1/gauges/{site}/ratings"
    response = requests.get(url, params={"onlyTenths": str(onlyTenths).lower()})
    response.raise_for_status()
    return response.json()["data"]

def get_bankfull_flows(cp_data):
    bankfull_flows_dict = {}
    cp_data = cp_data.copy()
    for row in cp_data.itertuples():
        name = row.ControlPoint
        site = row.ControlPointID
        stage = row.BankfullStage
        rating_curve = get_rating_table(site)
        stages = np.array([r["stage"] for r in rating_curve], dtype=float)
        flows = np.array([r["flow"] for r in rating_curve], dtype=float)
        # Check for an exact match first
        exact_match = np.where(stages == stage)[0]
        if len(exact_match) > 0:
            flow = float(flows[exact_match[0]])
        else:
            f = interp1d(stages, flows, fill_value="extrapolate")
            flow = float(f(stage))

        if stage < stages.min() or stage > stages.max():
            print(f"{site} Stage {stage} outside rating table, extrapolated.")
        bankfull_flows_dict[name] = flow
    # add to config as a column:
    cp_data["BankfullFlow"] = cp_data["ControlPoint"].map(bankfull_flows_dict)
    return cp_data
        
def find_flooding_events(data_dict, cp_data):
    events = {}
    for row in cp_data.itertuples():
        control_point = row.ControlPoint.upper()
        bankfull = row.BankfullFlow
        if control_point not in data_dict:
            print(f'{control_point} not found in data_dict')
            continue
        df = data_dict[control_point]
        # Identify event starts
        above_flow = df["value"] > bankfull
        event_starts = above_flow & ~above_flow.shift(1, fill_value=False)
        # Store event start timestamps
        events[control_point] = df.index[event_starts].tolist()
    # Convert dictionary to DataFrame, with locations as columns
    events_df = pd.DataFrame({
        loc: pd.Series(timestamps, dtype="datetime64[ns]")
        for loc, timestamps in events.items()})
    return events_df

def plot_flooding_events(data_dict, cp_data, selected_events_df):
    '''
    Plot event hydrographs.
    '''
    cp_data = cp_data.copy()
    cp_data = cp_data.dropna(subset=["LeadTime"])
    for row in cp_data.itertuples():
        cp = row.ControlPoint
        lead_time = row.LeadTime
        bankfull = row.BankfullFlow
        df = data_dict[cp.upper()]
        events = selected_events_df[cp.upper()].dropna()
        for event in events:
            start_time = event - pd.Timedelta(days=lead_time)
            # end_time = event + pd.Timedelta(days=7)
            end_time = event + pd.Timedelta(days=1)
            # Data leading up to and including the event
            event_lead_time_df = df.loc[start_time:event]
            # Data after the event, up to 7 days later
            post_and_pre_event_df = df.loc[(start_time-pd.Timedelta(days=2)):end_time]
            fig, ax = plt.subplots(figsize=(7, 5))
            # Before and during the event: dark blue
            ax.plot(event_lead_time_df.index, event_lead_time_df["value"], linewidth=2, color="steelblue", label="Lead Time", zorder=3)
            # After the event: light blue
            ax.plot(post_and_pre_event_df.index, post_and_pre_event_df["value"], linewidth=2, color="lightblue", label = "Event", zorder=2)
            # Mark the event time
            ax.axvline(event, color="gray", linestyle="--", linewidth=1.2, label="Bankfull Reached", zorder=1)
            # add bankfull 
            ax.axhline(y=bankfull, color="red", linestyle="--", linewidth=1.5, label=f"Bankfull ({bankfull} cfs)")
            ax.set_title(f"{cp} - {event.strftime('%B %d, %Y')}")
            ax.set_xlabel("Date")
            ax.set_ylabel("Flow (cfs)")
            ax.grid(True, linestyle="--", alpha=0.5)
            # readable date labels
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
            ax.xaxis.set_major_locator(mdates.AutoDateLocator())
            ax.legend()
            fig.autofmt_xdate(rotation=30)
            # save fig 
            plt.tight_layout()
            fig.savefig(f"../output/{cp}/{cp}_{event.strftime('%Y-%m-%d')}.png")
        
def find_event_volumes(data_dict, cp_data, selected_events_df):
    event_volumns = {}
    for row in cp_data.itertuples(): 
        name = row.ControlPoint
        lead_time_days = row.LeadTime # days to control point
        bankfull_cfs = row.BankfullFlow
        # Find the total volume available in the channel for the event lead up time:  
        lead_time_hrs = lead_time_days * 24
        channel_volume_kaf = cfs_to_kaf(bankfull_cfs, timestep_hr=lead_time_hrs)    
            
        if name.upper() not in data_dict: # skip if control point isn't in data_dict
            print(f'{name.upper()} not found in data_dict')
            continue
        df = data_dict[name.upper()]
        data = []
        if pd.isna(lead_time_days): # skip if there's no lead time for the control point 
            print(f"No lead time found for {name}")
            continue
        else: 
            events = selected_events_df[name].dropna() # get all the events for the control point
            for event in events: # loop though each event
                start_time = event - pd.Timedelta(days=lead_time_days) # start time is time bankfull is reached, minus lead time
                event_lead_time_df = df.loc[start_time:event] # isolate event
                if event_lead_time_df.isna().any().any(): # give a warning if nans, should be a complete record
                    print(f"Warning: Missing values in {name} between {start_time} and {event}")
                else: 
                    # find volume in of the event in kaf
                    event_volume_kaf = event_lead_time_df.apply(cfs_to_kaf).sum().iloc[0]
                    # find available FIRO volume 
                    available_volume_kaf = channel_volume_kaf - event_volume_kaf 
                    # Find event Magntude
                    # get two days before event, seven days after event
                    peak_start_time = event - pd.Timedelta(days=2)
                    peak_end_time = event + pd.Timedelta(days=7)
                    event_peak_df = df.loc[peak_start_time:peak_end_time] 
                    # convert to KAF
                    event_peak_kaf = event_peak_df.apply(cfs_to_kaf)
                    # Find the largest three-day volume
                    event_magnatude = event_peak_kaf.rolling(window=3).sum().max().iloc[0]
                    data.append((event, available_volume_kaf, event_magnatude)) # save to rows 
            df_out = pd.DataFrame(data, columns=['event', 'available_volume_kaf', "event_magnitude_kaf"]) # save to df
        event_volumns[name] = df_out # save all control point df to a dictionary 
    return event_volumns
            
def write_to_dss(DSS_OUT, event_volumes):
    """
    """
    for control_point, df in event_volumes.items():
        for col in ['available_volume_kaf','event_magnitude_kaf']:
            print(f"Processing: {control_point}")
            if col == 'available_volume_kaf':
                f_part = "FIRO_SPACE"
            elif col == "event_magnitude_kaf":
                f_part = "EVENT_MAGNATUDE"
            else:
                continue
            pathname = f'//{control_point.upper()}/VOLUME//IR-CENTURY/{f_part}'
            # Create the time series container
            tsc = TimeSeriesContainer(pathname=pathname, count=len(df), interval=-1)
            tsc.times = list(df['event'])
            tsc.values = df[col].to_numpy()
    
            # Set units based on the path
            tsc.data_units = "KAF"
            # Set the type 
            tsc.data_type = "INST"  
            tsc.tzid = "UTC"
            # Write the data to the DSS file
            with HecDss.Open(DSS_OUT, version=7) as fid:
                fid.put_ts(tsc)

def plot_FIRO_space_vs_event_magnitude(event_volumes):
    for control_point, df in event_volumes.items():
        plt.figure(figsize=(6, 6))
        plt.scatter(df['available_volume_kaf'], df['event_magnitude_kaf'], alpha=0.7)
        plt.xlabel('Available Volume (KAF)')
        plt.ylabel('Event Magnitude (KAF)')
        plt.title(f'FIRO Space vs. Event Magnitude - {control_point}')
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.show()


######### Code starts 
if __name__ == "main" or __name__ == "__main__":
    if REDOWNLOAD_DATA:
        data_dict = load_data_dict(FLOW_DATA)
        with open(FLOW_PICKLE, "wb") as file:
            pickle.dump(data_dict, file)
    else: 
        with open(FLOW_PICKLE, 'rb') as file:
            data_dict = pickle.load(file)
    
    # Bring in data
    cp_data = pd.read_excel(CONFIG, sheet_name="control_points", skiprows=5)
    cp_data = get_bankfull_flows(cp_data) # Add bankfull values to config
    # Output bankfull data
    bankfull_df = cp_data[['ControlPoint','ControlPointID','BankfullStage','BankfullFlow']].set_index("ControlPoint")
    bankfull_df.to_csv(BANKFULL_CSV)
    
    # find all events (places where bankfull is exceeded)
    detected_events_df = find_flooding_events(data_dict, cp_data)
    
    # plot events for QAQC purposes
    # plot_flooding_events(data_dict, cp_data, detected_events_df)
    # Read in selected events 
    selected_events_df = pd.read_excel(CONFIG, sheet_name="events", skiprows=5)

    # find all event volumes 
    event_volumes = find_event_volumes(data_dict, cp_data, selected_events_df)
    
    # write out the data for ssp purposes
    # write_to_dss(DSS_OUT, event_volumes)
    # write out to pickle 
    with open(EVENT_VOLUME_PICKLE, "wb") as file:
        pickle.dump(event_volumes, file)
    

