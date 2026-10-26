"""
Contains code to estimate routing times between points in the Willamette
As well as the time it takes reservoirs to ramp up/down releases
For FIRO. 

Ryan Cahill
July 2026

"""

# Resolve shared inputs and local outputs independently of the working directory.
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parent
SHARED_DATA = REPOSITORY_ROOT / "SHARED_DATA"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
MODULE_PATH = str(REPOSITORY_ROOT / "modules")
if MODULE_PATH not in sys.path:
    sys.path.insert(0, MODULE_PATH)

import pandas as pd
import numpy as np
import pickle
import datetime
import copy
from scipy import interpolate
from scipy import stats
from scipy.stats import norm, uniform
from numpy import log10
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator, AutoMinorLocator, LinearLocator, PercentFormatter, FixedLocator
from matplotlib.dates import DateFormatter
import matplotlib.dates as mdates
from matplotlib.patches import Patch
import datetime
from datetime import timedelta
from utilsDSS import HecDss
from ProbabilityDistributions import LP3Dist, fitLP3Dist, ppfLP3, cdfLP3
from Utils_Plots import normProbPlot, addLegendAtBottomOfSubplots
import statsmodels.api as sm
from scipy.interpolate import interp1d
from scipy.optimize import brentq
from joblib import Parallel, delayed
import HydrologicRouting

from pandas.plotting import register_matplotlib_converters
register_matplotlib_converters()

###############################################################################
#CONFIGURATION

CONFIG_FILE = PROJECT_ROOT / "config/LagConfig.xlsx"
ROUTING_PARAM_FILE = SHARED_DATA / "common_data/RoutingParams.xlsx"
RAMP_RATE_FILE = SHARED_DATA / "common_data/RampRates.xlsx"
DSS_IN_FILE = str(SHARED_DATA / "HourlyObservedInputs.dss")
DSS_LOCALFLOW_FILE = str(SHARED_DATA / "MeldedHourlyDaily_WY1982-2019.dss")
NAME_ALIAS = SHARED_DATA / "common_data/LocationAlias.xlsx"

FORCE_RELOAD = True
DATA_PICKLE_FILE = OUTPUT_DIRECTORY / "AllData.pickle"
UNREG_PICKLE_FILE = OUTPUT_DIRECTORY / "UnregFlows.pickle"

USE_MULTI_THREAD = True

################################################################################
# CLASS DEFINITIONS
    


################################################################################
# FUNCTION DEFINITIONS

def readAllData(dfTravelTimeReaches, dfEvents, dfAlias):
    '''
    Reads all time series data from dss and store it to a dataframe
    with index as datetime, and column names are the locations
    '''
    dictLocType = dict(zip(dfAlias["NAME"],dfAlias["POINT_TYPE"])) # "Reservoir" or "Junction"
    dssFile = HecDss.open(DSS_IN_FILE)
    print("Opening: %s" %DSS_IN_FILE)
    dfObs = pd.DataFrame()
    for j, dfLoc in dfTravelTimeReaches.iterrows():
        locNames = [dfLoc["Start_Location"], dfLoc["End_Location"]]
        for locName in locNames:
            if locName in dfObs: continue #already got it
            locType = dictLocType[locName]
            #pathname = dfLoc["DSS_path"]
            if locType == "Junction" or locName == "Willamette Falls":
                pathname = f"//{locName}/FLOW//1HOUR/BEST/"
            elif locType == "Reservoir":
                pathname = f"//{locName}/FLOW-OUT//1HOUR/BEST/"
            else:
                raise AssertionError("Unknown locType")
            print("  Reading: %s" %pathname)
            df = dssFile.readDF(pathname)
            if len(df) == 0: continue
            df = df.rename(columns={"value":locName})
            if len(dfObs) == 0:
                dfObs = df.copy()
            else: #tack on another column
                dfObs = pd.merge(dfObs, df, how="outer", left_index=True, right_index=True)
    dssFile.close()
    return dfObs

def xAxisSeasonal(ax):
    '''
    Puts the x-axis with ticks at each month, with the month label in between
    '''
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonthday=16))
    ax.xaxis.set_minor_formatter(mdates.DateFormatter('%b')) 
    ax.set_xticklabels('')
    ax.tick_params(which='minor', length=0)
    return ax

def getLagTimes(dfObs, dfTravelTimeReaches, dfEvents):
    """
    Returns a dataframe with lag times (hours)
    Each row is an event, and each column is a location pair (e.g. "Harrisburg_Albany")
    """
    rows = []
    for i, rowEvent in dfEvents.iterrows():
        eventName = rowEvent["EventName"]
        startTime = rowEvent["StartTime"]
        endTime = rowEvent["EndTime"]
        dfEvent = dfObs.loc[(dfObs.index >= startTime) & (dfObs.index <= endTime)]
        if dfEvent.isna().all().all(): #No data at all
            continue
        row = [eventName]
        cols = ["EventName"]
        for j, rowTravelTimeReach in dfTravelTimeReaches.iterrows():
            upLoc = rowTravelTimeReach["Start_Location"]
            downLoc = rowTravelTimeReach["End_Location"]
            colName = rowTravelTimeReach["Travel_Time_Reach_Name"]
            cols.append(colName)
            peakTimeUp = dfEvent[upLoc].idxmax() if dfEvent[upLoc].notna().any() else np.nan
            peakTimeDown = dfEvent[downLoc].idxmax() if dfEvent[downLoc].notna().any() else np.nan
            if pd.isna(peakTimeUp) or pd.isna(peakTimeDown):
                lagHours = np.nan
            else:
                lagHours = (peakTimeDown - peakTimeUp).total_seconds()/3600
            row.append(lagHours)
        rows.append(row)
    
    dfLag = pd.DataFrame(rows, columns=cols)
    #Add the median
    dfLag = dfLag.set_index("EventName")
    dfLag.loc["Median"] = dfLag.median()
    #Add the hours estimate from the sop stick diagram
    dfLag.loc["StickDiagram"] = dfTravelTimeReaches["SOP_Hours"].values
    dfLag = dfLag.reset_index("EventName")
    return dfLag

def getHeadwaterJunctions(dfReaches):
    """Returns a list of all headwater junction names"""
    dsJuncs = list(dfReaches["Downstream_Junction"].unique())
    allUpstreamJuncs = list(dfReaches["Upstream_Junction"].unique())
    hwJunctions = []
    for junc in allUpstreamJuncs:
        if junc not in dsJuncs:
            hwJunctions.append(junc)
    return hwJunctions

def buildReaches(dfReaches, dfMuskingum, dfModPuls, timestepHrs):
    """
    Loop along all reaches, building either a ModPulsReach, NullReach, or MuskingumReach
    Returns a dictionary with keys as reach name, values as reach objects (from HydrologicRouting.py)
    Good to do this upfront to see if there are any issues with the input before starting the compute.
    """
    reachDict = {}
    for i, row in dfReaches.iterrows():
        reachName = row["ReachName_HMS"]
        routingMethod = row["Method"]
        numberSubreaches = row["NumSubreaches"]
        routingID = row["RoutingID"]
        if pd.isna(routingMethod) or "NULL" in routingMethod.upper():
            reachObj = HydrologicRouting.NullReach()
        elif "MODPULS" in routingMethod.upper():
            df = dfModPuls[dfModPuls["RoutingID"]==routingID]
            if len(df) == 0: #couldn't find the routing reach
                raise AssertionError("Couldn't find the ModPuls Routing Parameters for: %s, routing ID: %s. Check the input file." %(reachName, routingID))
            storageList = sorted(df["Storage"].values)
            dischargeList = sorted(df["Discharge"].values)
            reachObj = HydrologicRouting.ModPulsReach(storageList, dischargeList, numberSubreaches)
            reachObj.setTimeStepSeconds(timestepHrs*60*60)
        elif "MUSKINGUM" in routingMethod.upper():
            df = dfMuskingum[dfMuskingum["RoutingID"]==routingID]
            if len(df) == 0: #couldn't find the routing reach
                raise AssertionError("Couldn't find the Muskingum Routing Parameters for: %s, routing ID: %s. Check the input file." %(reachName, routingID))
            K = df["K"].values[0]
            X = df["X"].values[0]
            reachObj = HydrologicRouting.MuskingumReach(K, X, numberSubreaches, timestepHrs = timestepHrs)
        else:
            raise AssertionError("Invalid routing method defined: %s" %row)
        reachDict[reachName] = reachObj
    return reachDict            

def readLocalFlowsData(dfLocalFlowMapping, dfEvents):
    '''
    Reads all time series data from dss and store it to a dataframe
    with index as datetime, and column names are the locations
    dictionary key is event name, value is dataframe
    '''
    dictLocalFlows = {}
    dssFile = HecDss.open(DSS_LOCALFLOW_FILE)
    print("Opening: %s" %DSS_LOCALFLOW_FILE)
    for i, rowEvent in dfEvents.iterrows():
        eventName = rowEvent["EventName"]
        startTime = rowEvent["StartTime"]
        endTime = rowEvent["EndTime"]
        if startTime.year < 1980: continue #No data
        dfLocalFlows = pd.DataFrame()
        for j, rowLoc in dfLocalFlowMapping.iterrows():
            junctionName_HMS = rowLoc["JunctionName_HMS"]
            aPart = rowLoc["aPart"].strip()
            bPart = rowLoc["bPart"]
            cPart = rowLoc["cPart"]
            ePart = rowLoc["ePart"]
            fPart = rowLoc["fPart"]
            pathname = f"/{aPart}/{bPart}/{cPart}//{ePart}/{fPart}/"
            print("  Reading: %s" %pathname)
            df = dssFile.readDF(pathname, startTime, endTime)
            df = df.rename(columns={"value":junctionName_HMS})
            if len(dfObs) == 0:
                dfLocalFlows = df.copy()
            else: #tack on another column
                dfLocalFlows = pd.merge(dfLocalFlows, df, how="outer", left_index=True, right_index=True)
        dictLocalFlows[eventName] = dfLocalFlows
    dssFile.close()
    return dictLocalFlows

def routeBasinWideFlows(dfReaches, dfLocalFlows, reachDict, dfObs):
    """
    Calculates routed flows at all reaches/junctions
    Helpful for shortcuts when trying different reservoir outflow patterns
    (Don't need to re-route the entire Santiam if looking at Lookout Point change)
     
    dfObs is a dataframe of observed flows where the routed will be "reset" and replaced with observed flows
    If you want to do unregulated, just supply an empty dataframe for dfObs
    
    output has naming convention of HMS junctions, not nice names
    """
    
    dfObsEvent = dfObs.loc[dfLocalFlows.index]
    if len(dfObsEvent) != len(dfLocalFlows):
        print("No observed data")
    dictObsName = dict(zip(dfAlias["HMS_NAME"], dfAlias["NAME"]))
    hwJunctions = getHeadwaterJunctions(dfReaches)
    #Initialize the dataframe with routed flows. Starts out as 0 for every single location as a column
    allCols = pd.concat([dfReaches["Downstream_Junction"], dfReaches["Upstream_Junction"], dfReaches["ReachName_HMS"]]).unique()
    dfObsRouted = pd.DataFrame(index=dfLocalFlows.index, columns = allCols, data=0)
    for i, row in dfReaches.iterrows():
        reachName = row["ReachName_HMS"]
        junctionNameUS = row["Upstream_Junction"]
        junctionNameDS = row["Downstream_Junction"]
        #At headwater points, start it up
        if junctionNameUS in hwJunctions:
            dfObsRouted[junctionNameUS] = 0
        #Add in the local flows to the upstream point if they exist.
        if junctionNameUS in dfLocalFlows:
            dfObsRouted[junctionNameUS] += dfLocalFlows[junctionNameUS]
        #Replace with observed timeseries if it exists (uses different naming convention)
        if junctionNameUS in dictObsName:
            junctionNameObs = dictObsName[junctionNameUS]
            if junctionNameObs in dfObsEvent:
                if not dfObsEvent[junctionNameObs].isna().any():
                    # A complete record, use it
                    dfObsRouted[junctionNameUS] = dfObsEvent[junctionNameObs]
        #Do the routing after replacing any negative values with 0
        routedFlows = reachDict[reachName].routeHydrograph(dfObsRouted[junctionNameUS].clip(lower=0))
        #Save the routed flows
        dfObsRouted[reachName] = routedFlows
        #Add the routed flows to the downstream junction
        dfObsRouted[junctionNameDS] += routedFlows
    #At the very downstream end, add in any local flows
    dfObsRouted[junctionNameDS] += routedFlows
    return dfObsRouted


def routeDownstream(dfReaches, dfLocalFlows, reachDict, startLocation, seriesStart, dfFlowsBasinWide):
    """
    

    Parameters
    ----------
    dfReaches : TYPE
        DESCRIPTION.
    dfLocalFlows : TYPE
        DESCRIPTION.
    reachDict : TYPE
        DESCRIPTION.
    startLocation : str
        Nice location name, e.g. ("Detroit" or "Mehama").
    seriesStart : series
        Timeseries of flows to start the routing, at startLocation.
    dfFlowsBasinWide : TYPE
        A dataframe with previously routed flows for the whole basin (can be observed or unreg)
        This dataframe will be used to add in tributary flows when routing downstream from startLocation.

    Returns
    -------
    dfRouted : DataFrame
        Routed flows at all control points downstream (standard naming conventions).

    """    

    #First, get only the reaches to route that are downstream from startLocation
    reachNamesToRoute = []
    dictHMSName = dict(zip(dfAlias["NAME"], dfAlias["HMS_NAME"]))
    currentJunction = dictHMSName[startLocation]
    for i, rowReach in dfReaches.iterrows():
        reachName = rowReach["ReachName_HMS"]
        upJunc = rowReach["Upstream_Junction"]
        downJunc = rowReach["Downstream_Junction"]
        if currentJunction == upJunc:
            reachNamesToRoute.append(reachName)
            currentJunction = downJunc
    dfDSReaches = dfReaches.loc[dfReaches["ReachName_HMS"].isin(reachNamesToRoute)]
    dfTribReaches = dfReaches.loc[~dfReaches["ReachName_HMS"].isin(reachNamesToRoute)]
    
    #Next, do the routing of the input hydrograph
    #Initialize the dataframe with routed flows. Starts out as 0 for every single downstream location as a column
    allCols = pd.concat([dfDSReaches["Upstream_Junction"], dfDSReaches["Downstream_Junction"]]).unique()
    dfRouted = pd.DataFrame(index=dfLocalFlows.index, columns = allCols, data=0)
    dfRouted[dictHMSName[startLocation]] = seriesStart
    #Now, do the routing
    for i, rowReach in dfDSReaches.iterrows():
        reachName = rowReach["ReachName_HMS"]
        junctionNameUS = rowReach["Upstream_Junction"]
        junctionNameDS = rowReach["Downstream_Junction"]
        #Do the routing after replacing any negative values with 0
        routedFlows = reachDict[reachName].routeHydrograph(dfRouted[junctionNameUS].clip(lower=0))
        #Add the routed flows to the downstream junction
        dfRouted[junctionNameDS] += routedFlows
        #Add in any local flows and flows from other tributary reaches
        if junctionNameDS in dfLocalFlows:
            dfRouted[junctionNameDS] += dfLocalFlows[junctionNameDS]
        #Add in any flows from other tributary reaches
        tribReaches = dfTribReaches.loc[dfTribReaches["Downstream_Junction"]==junctionNameDS]
        for k, rowTribReach in tribReaches.iterrows():
            reachNameTrib = rowTribReach["ReachName_HMS"]
            dfRouted[junctionNameDS] += dfFlowsBasinWide[reachNameTrib]
        
    #Return naming conventions back to standard ones, since this is just downstream junctions
    dfRouted = dfRouted.rename(columns=dict(zip(dfAlias["HMS_NAME"], dfAlias["NAME"])))
    #Drop all columns except ones that have standard naming conventions
    dfRouted = dfRouted.filter(dfAlias["NAME"])
    
    return dfRouted

def getRecessionTime(dfRoutedMin, dfRoutedMax, preReleaseStopTime, convergence_fraction = 0.10):
    """
    Given two dataframes with identical columns.
    dfRoutedMax is a condition where flow were at max release capacity, then suddenly drop to min flow
    dfRoutedMin is a condition where flows are at min flow constantly
    For each column (location), find the first date where the difference in flow drops below a certain percent
    If Mehama starts at 17000 cfs at simulation 1 and 11000 cfs at simulation 2,
    the difference is 6000 cfs.
    Find the first date the difference between the timeseries converges to x% of 6000
    convergence_fraction defaults to a 10% threshold
    Report the lag time from "preReleaseStopTime" (when releases are reduced) to that date we find
    
    Returns a dictionary with keys as location names and values as recession time in hours
    """

    dictRecessionTime = {}

    # Filter dataframes to only include entries at or after the preReleaseStopTime
    dfMin_after = dfRoutedMin[dfRoutedMin.index >= preReleaseStopTime]
    dfMax_after = dfRoutedMax[dfRoutedMax.index >= preReleaseStopTime]
    
    # Calculate the time difference series after the cutoff time
    df_diff_after = (dfMax_after - dfMin_after).abs()

    for location in dfRoutedMin.columns:
        # Calculate initial difference at the beginning of the timeseries (t=0)
        initial_diff = (dfRoutedMax.iloc[0] - dfRoutedMin.iloc[0]).abs().max()

        if initial_diff == 0:
            dictRecessionTime[location] = 0
            continue
            
        # Calculate the convergence threshold value
        convergence_threshold = initial_diff * convergence_fraction
        
        # Find the first time the difference drops below the threshold
        converged_series = df_diff_after[location][df_diff_after[location] <= convergence_threshold]

        if not converged_series.empty:
            convergence_time = converged_series.index[0]
            # Calculate lag time in hours
            lag_time_timedelta = convergence_time - preReleaseStopTime
            lag_time_hours = lag_time_timedelta.total_seconds() / 3600
            dictRecessionTime[location] = lag_time_hours
        else:
            # If it never converges, store None for that location
            dictRecessionTime[location] = None
    
    return dictRecessionTime

def runResvLagsOneEvent(eventName, preReleaseStopTime):
    """
    Returns a dataframe with the lag times from each reservoir to each downstream point
    That result when cutting back from max release to min release.

    """
    dfLocalFlows = dictLocalFlows[eventName]
    #Get routed observed flows everywhere upfront to save time when doing mini-simulations
    dfFlowsBasinWide = routeBasinWideFlows(dfReaches, dfLocalFlows, reachDict, dfObs)
    
    rows = []
    for j, rowResv in dfResvMaxRel.iterrows():
        startLocation = rowResv["Reservoir"]
        normMaxRel = rowResv["NormMaxRel"]
        minRel = rowResv["MinRel"]
        #Do a mini-simulation with release set to min flow
        seriesStart = pd.Series(index=dfFlowsBasinWide.index, data=minRel)
        dfRoutedMin = routeDownstream(dfReaches, dfLocalFlows, reachDict, startLocation, seriesStart, dfFlowsBasinWide)
        #Do a 2nd mini-simulation with release at max rates until a certain date, where it reverts to min rel
        #Replace values with max release up to a date
        seriesStart.loc[seriesStart.index<preReleaseStopTime] = normMaxRel
        dfRoutedMax = routeDownstream(dfReaches, dfLocalFlows, reachDict, startLocation, seriesStart, dfFlowsBasinWide)
        
        #Find how long it takes for the flow at downstream points to recess to 90% of the difference
        dictRecessionTime = getRecessionTime(dfRoutedMin, dfRoutedMax, preReleaseStopTime)
        
        for dsLocation in dfRoutedMax.columns:
            if dsLocation == startLocation: continue    
            rows.append([startLocation, dsLocation, eventName, dictRecessionTime[dsLocation]])
    
    colNames = ["Reservoir", "Downstream Location", "Event", "Lag (Hours)"]
    dfReservoirLags = pd.DataFrame(columns=colNames, data=rows)

    '''
    #Just some diagnostic plotting, delete
    dfObsEvent = dfObs.loc[dfLocalFlows.index]
    
    for locName in ["Big Cliff", "Mehama", "Jefferson"]:
        dictHMSName = dict(zip(dfAlias["NAME"], dfAlias["HMS_NAME"]))
        hmsName = dictHMSName[locName]
        fig, ax = plt.subplots()
        ax.plot(dfObsEvent.index, dfObsEvent[locName], color="tab:blue",label="Observed")
        ax.plot(dfFlowsBasinWide.index, dfFlowsBasinWide[hmsName], color="tab:orange", ls="dashed", label="Routed observed")
        ax.plot(dfRouted.index, dfRouted[locName], color="tab:purple", label="Routed")
        ax.legend()
    '''
    
    return dfReservoirLags

def getResvLagMedians(dfEvents):

    calls = []
    dfList = []
    for i, rowEvent in dfEvents.iterrows():
        eventName = rowEvent["EventName"]
        if not eventName in ["Feb 1996", "Nov 1996", "Jan 1997", "Dec 1998", "Jan 2006", "Jan 2012", "Apr 2019"]: continue
        print(eventName)
        preReleaseStopTime = rowEvent["PreReleaseStopTime"]
        if USE_MULTI_THREAD:
            calls.append(delayed(runResvLagsOneEvent)(eventName, preReleaseStopTime))
        else:
            dfList.append(runResvLagsOneEvent(eventName, preReleaseStopTime))
        
    if USE_MULTI_THREAD:      
        #Have to set max_nbytes because of some odd issue here:
        #https://github.com/joblib/joblib/issues/806
        dfList = Parallel(n_jobs=-2, max_nbytes=None)(calls)          
    dfReservoirLags = pd.concat(dfList)
    #runResvLagsOneEvent(eventName, preReleaseStopTime)
    
    #Create a summary table with reservoirs as rows, downstream locations as columns
    dfResvLagMedians = dfReservoirLags.pivot_table(
                    index='Reservoir',
                    columns='Downstream Location',
                    values='Lag (Hours)',
                    aggfunc='median')/24 #convert to days
    #Re-order the columns and rows
    colOrder = ["Goshen", "Vida", "Jasper", "Monroe", "Waterloo","Mehama","Jefferson","Harrisburg", "Albany","Salem", "Willamette Falls"]
    rowOrder = ["Cottage Grove", "Dorena", "Blue River", "Cougar", "Hills Creek","Lookout Point","Fall Creek", "Fern Ridge", "Green Peter", "Foster", "Detroit"]
    dfResvLagMedians = dfResvLagMedians[colOrder].loc[rowOrder]
    
    return dfReservoirLags, dfResvLagMedians

def plotExampleRouting():
    
    '''
    #Just some diagnostic plotting showing both mini simulations
    '''
    eventName = "Jan 2012"
    resvName = "Detroit"
    dsLocNames = ["Detroit", "Mehama", "Salem"]
    preReleaseStopTime = datetime.datetime(2012,1,18)
    
    dfLocalFlows = dictLocalFlows[eventName]
    #Get routed observed flows everywhere upfront to save time when doing mini-simulations
    dfFlowsBasinWide = routeBasinWideFlows(dfReaches, dfLocalFlows, reachDict, dfObs)
    
    startLocation = resvName
    rowResv = dfResvMaxRel.loc[dfResvMaxRel["Reservoir"]==resvName].iloc[0].to_dict()
    normMaxRel = rowResv["NormMaxRel"]
    minRel = rowResv["MinRel"]
    #Do a mini-simulation with release set to min flow
    seriesStart = pd.Series(index=dfFlowsBasinWide.index, data=minRel)
    dfRoutedMin = routeDownstream(dfReaches, dfLocalFlows, reachDict, startLocation, seriesStart, dfFlowsBasinWide)
    #Do a 2nd mini-simulation with release at max rates until a certain date, where it reverts to min rel
    #Replace values with max release up to a date
    seriesStart.loc[seriesStart.index<preReleaseStopTime] = normMaxRel
    dfRoutedMax = routeDownstream(dfReaches, dfLocalFlows, reachDict, startLocation, seriesStart, dfFlowsBasinWide)
    
    #Make plots
    for locName in dsLocNames:
        fig, ax = plt.subplots()
        ax.plot(dfRoutedMin.index, dfRoutedMin[locName], color="tab:blue",label="Detroit at Min Release")
        ax.plot(dfRoutedMax.index, dfRoutedMax[locName], color="tab:orange", ls="dashed", label="Detroit Max Release, then Cutback to Min")
        if locName =="Detroit":
            ax.plot(dfLocalFlows.index, dfLocalFlows["Detroit_Out"], color="tab:pink", label="Detroit Inflow")
        else:
            ax.plot(dfRoutedMax.index, dfRoutedMax[locName] - dfRoutedMin[locName], color="tab:purple", label="Difference")
        ax.axvline(preReleaseStopTime, color="gray", ls="dotted")
        ax.set_ylabel("Flow (cfs)")
        ax.set_ylim([0, ax.get_ylim()[-1]])
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b-%d')) 
        ax.legend() 
        plt.suptitle(locName)
        plt.tight_layout()

def getRampPerHour(dfRamp, curRel, normMaxRel):
    '''
    Returns the maximum ramp rate in cfs per hour

    Parameters
    ----------
    dfRamp : Dataframe
        dataframe with ramp rates for one project, regime, and up/down.
    curRel : float
        The current release (cfs) to use when interpolating what the ramp rate can be for this hour.

    '''
    if len(dfRamp) == 1:
        if dfRamp["RampPerHour_Pct"].isna().any():
            rampCFS = dfRamp["RampPerHour_CFS"].iloc[0]
        else: 
            #a percent, assume this is % of max release.
            #Otherwise, if we kept doing 20% using current release, we'd never get to zero
            rampCFS = dfRamp["RampPerHour_Pct"].iloc[0] * normMaxRel
    else:
        #Ramp rate has various flow ranges
        rampCFS = np.nan
        for j, rowRamp in dfRamp.iterrows():
            if rowRamp["FlowRange_Low"] <= curRel < rowRamp["FlowRange_High"]:
                rampCFS = rowRamp["RampPerHour_CFS"]
        if rampCFS == np.nan:
            raise AssertionError("Input flow outside the bounds of the table")
    return rampCFS

def calcRampTimes(dfRampRates, dfResvMaxRel):
    """
    Returns a dataframe with the time it takes for each reservoir to ramp up/down from min flow to max evacuation release

    """
    
    rows = []
    for resvName in dfRampRates["Project"].unique():
        rowResv = dfResvMaxRel.loc[dfResvMaxRel["Reservoir"]==resvName].iloc[0].to_dict()
        normMaxRel = rowResv["NormMaxRel"]
        minRel = rowResv["MinRel"]
        
        for regimeType in ["High Flow"]: #, "BiOp"]:
            #Do the increasing ramp
            dfRamp = dfRampRates.loc[(dfRampRates["Project"]==resvName) & 
                                     (dfRampRates["Regime"]==regimeType) & 
                                     (dfRampRates["UpOrDown"]=="Up")]
            curRel = minRel
            rampHours = 99
            for i in range(99): #shouldn't go more than 99 hours
                rampCFS = getRampPerHour(dfRamp, curRel, normMaxRel)
                curRel = curRel + rampCFS
                if curRel >= normMaxRel:
                    rampHours = i+1
                    break
            rows.append([resvName, regimeType, "Up", rampHours])
            
            #Do the decreasing ramp
            dfRamp = dfRampRates.loc[(dfRampRates["Project"]==resvName) & 
                                     (dfRampRates["Regime"]==regimeType) & 
                                     (dfRampRates["UpOrDown"]=="Down")]
            curRel = normMaxRel
            rampHours = 99
            for i in range(99): #shouldn't go more than 99 hours
                rampCFS = getRampPerHour(dfRamp, curRel, normMaxRel)
                curRel = curRel - rampCFS
                if curRel <= minRel:
                    rampHours = i+1
                    break
            rows.append([resvName, regimeType, "Down", rampHours])
    dfRampTimes = pd.DataFrame(columns=["Reservoir","Regime","UpOrDown","RampHours"], data=rows)
    return dfRampTimes

def getTypicalWinterUnreg(resvNames, dictLocalFlows, percentile = 0.75):
    """
    Get typical winter unreg flow for all reservoirs
    Takes a percentile of the November-March flows
    Useful for figuring out how long it takes to evacuate storage

    """
    with open(UNREG_PICKLE_FILE, 'rb') as f:
        dfUnreg = pickle.load(f) 
    dictTypicalWinterInflow = dfUnreg.loc[(dfUnreg.index.month >= 11) | 
                                          (dfUnreg.index.month <= 3)].quantile(percentile)
    return dictTypicalWinterInflow

def getTimeToEvacuate(evacStorKAF, inflow, minRel, normMaxRel, rampHours):
    """
    Calc time to evacuate a given FIRO space above rule curve, given parameters
    Assumes a trapezoidal shape for releases, where they ramp up from min flow to max flow,
    Then back down to min release at the end

    Parameters
    ----------
    evacStorKAF : float
        amount of storage to evacuate.
    inflow : float
        Assumed constant inflow
    minRel : float
        Minimum release for the project.
    normMaxRel : float
        Max evacuation release for the project.
    rampHours : float
        Total of ramp up and ramp down time from min and max releases.

    Returns
    -------
    evacTimeHrs : TYPE
        Hours to evacuate the evacStorKAF.

    """
    
    cfsHoursToKAF = (60*60)/43560/1000
    
    #Do some algebra to figure out how long it takes, assuming a trapezoidal shape of release, flat inflows
    volCfsHours = evacStorKAF / cfsHoursToKAF
    trapHeight = normMaxRel - minRel
    evacTimeHrs = (volCfsHours + rampHours*trapHeight/2)/(minRel - inflow + trapHeight)
    
    return evacTimeHrs

def getEvacTimeDict(dictTypicalWinterInflow, pctOfConStor=0.20):
    """
    Returns dictionary showing how long it would take to evacuate a given amount
    of storage, expressed as a percent of total conservation storage.
    At Lookout Point, this also assume Hills Creek is also evacuating storage
    
    keys are reservoirs, values are times in days

    """
    dictEvacTime = {}
    for i, rowResv in dfResvMaxRel.iterrows():
        resvName = rowResv["Reservoir"]
        normMaxRel = rowResv["NormMaxRel"]
        minRel = rowResv["MinRel"]
        conStorKAF = rowResv["ConStorKAF"]
        inflow = dictTypicalWinterInflow[resvName]
        rampUpHours = dfRampTimesSummary["Up"].loc[resvName]
        rampDownHours = dfRampTimesSummary["Down"].loc[resvName]
        rampHours = rampUpHours + rampDownHours
        evacStorKAF = conStorKAF*pctOfConStor
        evacTimeHrs = getTimeToEvacuate(evacStorKAF, inflow, minRel, normMaxRel, rampHours)
        dictEvacTime[resvName] = evacTimeHrs/24 #convert to days
        if resvName == "Lookout Point": 
            #Do combined Hills Creek/Lookout Point also
            #Bump up the space to include both, but stick with LOP's max release
            conStorKAF = conStorKAF + dfResvMaxRel.loc[dfResvMaxRel["Reservoir"]=="Hills Creek"]["ConStorKAF"].iloc[0]
            evacStorKAF = conStorKAF*pctOfConStor
            evacTimeHrs = getTimeToEvacuate(evacStorKAF, inflow, minRel, normMaxRel, rampHours)
            dictEvacTime["Lookout Point+Hills Creek"] = evacTimeHrs/24 #convert to days
    return dictEvacTime

def plotEvacTimes(dictEvacTime, pctOfConStor=0.20):
    """
    Simple plot showing evac times as a bunch of straight lines, one for each project
    """
    
    dfPlot = pd.DataFrame()
    dfPlot["Reservoir"] = dictEvacTime.keys()
    dfPlot["Value"] = dictEvacTime.values()
    dfPlot = dfPlot.sort_values("Value", ascending=False)
    
    resvNames = dfPlot["Reservoir"].to_list()
    fig, ax = plt.subplots(figsize = (9, 6.5))
    for resvName in resvNames:
        if resvName == "Foster": continue
        if resvName == "Lookout Point+Hills Creek":
            ax.plot([0,pctOfConStor],[0,dictEvacTime[resvName]], label=resvName, color="black")
        else:
            ax.plot([0,pctOfConStor],[0,dictEvacTime[resvName]], label=resvName)
        
    ax.set_ylabel("Time (days)")
    ax.set_xlabel("Percent of total conservation storage to evacuate")
    ax.xaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=None))
    ax.set_xlim([0,pctOfConStor])
    ax.set_ylim([0,dfPlot["Value"].max()])
    ax.legend()
 
def plotEvacTimeByPercentile():
    """
    Varies the unregulated inflow percentile and shows how evacuation
    time at LOS+HCR changes
    Produces a simple graph
    """
    dfPlot = pd.DataFrame(columns=["WinterUnregPercentile","Evacuation_Time"])
    for winterUnregPercentile in np.arange(0.10,0.91, 0.01):
        dictTypicalWinterInflow = getTypicalWinterUnreg(resvNames, dictLocalFlows, percentile=winterUnregPercentile)
        dictEvacTime = getEvacTimeDict(dictTypicalWinterInflow, pctOfConStor=0.10)
        dfPlot.loc[len(dfPlot)] = [winterUnregPercentile, dictEvacTime["Lookout Point+Hills Creek"]]
    fig, ax = plt.subplots()
    ax.plot(dfPlot["WinterUnregPercentile"], dfPlot["Evacuation_Time"])
    plt.suptitle("Lookout Point + Hills Creek")
    ax.set_ylabel("Time to evacuate 10% of conservation storage (days)")
    ax.set_xlabel("Inflow percentile during winter")
    ax.xaxis.set_major_formatter(PercentFormatter(xmax=1))
    

#####  Main  ###################################################################
# MAIN CODE
if __name__ == "main" or __name__ == "__main__":
    # Code starts here when called as script.  Otherwise can be loaded as a module
    # The DSS library creates empty files for missing paths; fail before opening inputs.
    for required_input in [DSS_IN_FILE, DSS_LOCALFLOW_FILE]:
        if not Path(required_input).is_file():
            raise FileNotFoundError(f"Required external DSS input is missing: {required_input}")
    # Read in the excel config file
    dfTravelTimeReaches = pd.read_excel(CONFIG_FILE, sheet_name="TravelTimeReaches", header = 5)
    dfTravelTimeReaches = dfTravelTimeReaches.loc[dfTravelTimeReaches["Compute?"]==True].copy()
    dfEvents = pd.read_excel(CONFIG_FILE, sheet_name="Events", header = 5)
    dfAlias = pd.read_excel(NAME_ALIAS, sheet_name="LocationAlias", header = 6)
    dfLocalFlowMapping = pd.read_excel(CONFIG_FILE, sheet_name="LocalFlows", header = 5)
    dfLocalFlowMapping = dfLocalFlowMapping.loc[dfLocalFlowMapping["JunctionName_HMS"] != "Nowhere"]
    dfResvMaxRel = pd.read_excel(CONFIG_FILE, sheet_name="ResvMaxRel", header = 5)
    dfRampRates = pd.read_excel(RAMP_RATE_FILE, sheet_name="RampRates", header = 5)
    dfReaches = pd.read_excel(ROUTING_PARAM_FILE, sheet_name="Reaches", header = 5, true_values=["Yes"], false_values=["No"]) 
    dfMuskingum = pd.read_excel(ROUTING_PARAM_FILE, sheet_name="Muskingum", header = 5)
    dfModPuls = pd.read_excel(ROUTING_PARAM_FILE, sheet_name="ModPuls", header = 5)
    #TODO hardcode: eliminate the Tualatin River above West Linn, to make it think West Linn is headwater
    dfReaches = dfReaches[~dfReaches["ReachName_HMS"].isin(["TualatinRv_R20", "TualatinRv_R10"])]
    #Build the skeleton of the routing model
    reachDict = buildReaches(dfReaches, dfMuskingum, dfModPuls, 1) #dictionary object with keys as reach name, values as reach objects (from HydrologicRouting.py)
    
    #Get the data
    if FORCE_RELOAD:
        #Read all data from dss and store to a pickle file
        dfObs = readAllData(dfTravelTimeReaches, dfEvents, dfAlias)
        with open(DATA_PICKLE_FILE, 'wb') as f:
            pickle.dump(dfObs, f)
    with open(DATA_PICKLE_FILE, 'rb') as f:
        dfObs = pickle.load(f) 
    #Method 1: Get lag times from observed data (no routing, just gage analysis)
    dfLag = getLagTimes(dfObs, dfTravelTimeReaches, dfEvents)
    dsColNames = []
    for colName in dfLag.columns:
        foundResv = False
        for resvName in dfResvMaxRel["Reservoir"].values:
            if resvName in colName:
                foundResv = True
        if foundResv == False:
            dsColNames.append(colName)
    dfLag = dfLag[dsColNames]

    #Read in local flows from DSS (HMS naming convention to line up with junctions)
    dictLocalFlows = readLocalFlowsData(dfLocalFlowMapping, dfEvents)  

    #Method 2: Get lag times from changing reservoir releases  
    dfReservoirLags, dfResvLagMedians = getResvLagMedians(dfEvents)
    dfResvLagMedians.to_csv(OUTPUT_DIRECTORY / "ResvLagTimes_Median.csv")
    
    #Get results at Detroit for demonstration
    dfLagsAllEvents = dfReservoirLags.loc[dfReservoirLags["Reservoir"]=="Detroit"].drop(columns="Reservoir")
    dfLagsAllEvents = dfLagsAllEvents.pivot(index='Event', columns='Downstream Location', values='Lag (Hours)')
    # Reorder columns to match original data order
    column_order = ['Mehama', 'Jefferson', 'Salem', 'Willamette Falls']
    dfLagsAllEvents = dfLagsAllEvents[column_order]
    
    #Some plots for demonstration
    plt.close('all')
    plotExampleRouting()

    #Calculate the time it takes to ramp up/down from min release to max release
    dfRampTimes = calcRampTimes(dfRampRates, dfResvMaxRel)
    dfRampTimesSummary = dfRampTimes.pivot(index="Reservoir",columns="UpOrDown",values="RampHours")
    
    #Calculate the time it takes a reservoir to evacuate FIRO space
    resvNames = dfResvMaxRel["Reservoir"].to_list()
    dictTypicalWinterInflow = getTypicalWinterUnreg(resvNames, dictLocalFlows, percentile=0.75)
    dictEvacTime = getEvacTimeDict(dictTypicalWinterInflow, pctOfConStor=0.20)
    dfEvacTimeCSV = pd.DataFrame(list(dictEvacTime.items()), columns=['Reservoir', 'EvacTimeDays'])
    dfEvacTimeCSV["PctConStorEvacuated"] = 0.20
    dfEvacTimeCSV.to_csv(OUTPUT_DIRECTORY / "ResvEvacTimes_75thPctInflow.csv",index=False)
    
    #Plot up the evacuation times for all reservoirs
    plotEvacTimes(dictEvacTime, pctOfConStor=0.20)
    
    #Calc evac times for various winter flow percentiles
    plotEvacTimeByPercentile()
    
