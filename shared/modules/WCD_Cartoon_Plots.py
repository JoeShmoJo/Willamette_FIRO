# -*- coding: utf-8 -*-
"""
Water control diagram cartoon plots
They show both storage (with 0=min con storage) and elevation on the right
Linear as a function of storage
Pool zones are shaded (e.g. flood pool, conservation pool)


"""

# Resolve shared inputs and local outputs independently of the working directory.
from pathlib import Path
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parent
SHARED_DATA = REPOSITORY_ROOT / "shared"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
MODULE_PATH = str(SHARED_DATA / "modules")
if MODULE_PATH not in sys.path:
    sys.path.insert(0, MODULE_PATH)


import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator, AutoMinorLocator, FixedLocator, LinearLocator, FormatStrFormatter, PercentFormatter, FuncFormatter, NullFormatter
import datetime

from Utils_Plots import xAxisSeasonal
from ProbabilityDistributions import LP3Dist, ppfLP3, cdfLP3
from Utils_Datetime import getDate2001, getWillYr


startDT = datetime.datetime(2000,8,1)
endDT = datetime.datetime(2001,7,31)

RULECURVE_CSV_FILE = SHARED_DATA / "common_data/Willamette_Rule_Curves.csv"
DRAWDOWNCURVE_CSV_FILE = SHARED_DATA / "common_data/Drawdown_Target_Curves.csv"
ELEV_STOR_CSV = SHARED_DATA / "common_data/ElevStor.csv"
RESERVOIR_ELEV_XLSX = SHARED_DATA / "common_data/Reservoirs.xlsx"

def elevToStor(elevInput, resvName):
    '''
    Converts elevation(s) to storage in units of kaf above minimum conservation 
    elevInput can be a number, a list, or an array

    '''
    dfES = dfElevStor.loc[dfElevStor["Reservoir"]==resvName]
    storGross = np.interp(elevInput, dfES["Elev"], dfES["Stor"])
    #Normalize so min conservation pool is 0 storage
    minConElev = resv_info_dict[resvName]["MinConElev"]
    minConStor = np.interp(minConElev, dfES["Elev"], dfES["Stor"])
    storOut = (storGross - minConStor)/1000
    return storOut

def storToElev(storInput, resvName):
    '''
    Reverse of elevToStor, storInput is in kaf above min con

    '''

    dfES = dfElevStor.loc[dfElevStor["Reservoir"]==resvName]
    minConElev = resv_info_dict[resvName]["MinConElev"]
    minConStor = np.interp(minConElev, dfES["Elev"], dfES["Stor"])
    storGross = storInput*1000 + minConStor
    elevOut = np.interp(storGross, dfES["Stor"], dfES["Elev"])
    return elevOut

def getIRRMLine(irrmElev, resvName, seriesRCStor):
    '''
    Given a series of rule curve storage,
    Return a series with the IRRM as a flat line (only portions below the rule curve)
    This is for seismic IRRM
    '''
    irrmStor = elevToStor(irrmElev, resvName)
    seriesIRRM = seriesRCStor.copy()
    seriesIRRM.loc[seriesRCStor.values < irrmStor] = np.nan
    seriesIRRM.loc[seriesRCStor.values >= irrmStor] = irrmStor
    #seriesIRRM.loc[:] = irrmStor
    return seriesIRRM

def yAxisStorAtKeyElevs(ax, resvName):
    '''
    Formats the y-axis the way we want it for stor
    If showElev=True, the secondary y-axis will show elevation
    '''
    keyElevColNames = ["MinElev","FullPoolElev","MinConElev","MaxConElev","MinPowerPool","InactivePool","IRRMElev","SpillwayCrest"]
    elevs = sorted(dfReservoirs.loc[dfReservoirs["ReservoirName"] == resvName, keyElevColNames].squeeze().dropna())
    stors = elevToStor(elevs, resvName)
    ax.yaxis.set_major_locator(FixedLocator(stors))
    ax.yaxis.set_major_formatter(FormatStrFormatter('%d'))
    #Add the elevations at right
    addSecondaryYLabelsElev(ax, resvName)

def addSecondaryYLabelsElev(ax, resvName):
    ax2 = ax.twinx()
    #ax2.spines["top"].set_visible(False)
    #ytick2 = ((fullPoolStor - interpElevStor(ytick))/1000).round(2)
    ax2.set_ylim(ax.get_ylim())
    ticksLeft = ax.get_yticks()
    elevs = storToElev(ticksLeft, resvName) 
    yRightLabels = ["%0.1f" %elev for elev in elevs]
    ax2.yaxis.set_major_locator(FixedLocator(ticksLeft))
    ax2.set_yticklabels(yRightLabels)
    ax2.set_ylabel("Elevation (ft, project datum)")

def cartoonWCD(resvName):
    '''
    Creates a cartoon-ish version of the water control diagram
    with the pools shaded different colors
    '''
    fig, ax = plt.subplots(figsize=[8, 4.5])
    ax.plot(dfRCStor[resvName], color='black')
    ax = xAxisSeasonal(ax)
    ax.set_xlim([dfRCStor.index[0], dfRCStor.index[-1]])
    ax.set_ylabel("Storage (kaf)")
    fig.suptitle(resvName)
    #Add a bunch of markers
    
    if resvName != "Foster":
        spillCrestElev = resv_info_dict[resvName]["SpillwayCrest"]
        spillCrestStor = elevToStor(spillCrestElev, resvName)
        ax.axhline(spillCrestStor, ls="dashed", color="gray", alpha=0.3, zorder=2)
        ax.text(dfRCStor.index[-2], elevToStor(spillCrestElev-0.5, resvName), "Spillway Crest", ha="right",va="top")
    
    #Shade the various pools
    
    #Flood pool
    fullStor = elevToStor(resv_info_dict[resvName]["FullPoolElev"], resvName)
    ax.fill_between(
        dfRCStor[resvName].index, 
        fullStor, 
        dfRCStor[resvName], 
        color='tab:blue',             # Selected soft color from the "Cool" palette
        alpha=0.4,                   # Transparency so background grid is visible
        zorder=1                     # Places the fill behind the boundary lines
    )
    ax.text(datetime.datetime(2001,1,1), 0.3*dfRCStor[resvName].max(), "Flood Pool", ha="center",va="center")
    
    #Seismic IRRM Pool
    seriesRCClipped = dfRCStor[resvName].copy()
    irrmElev = resv_info_dict[resvName]["IRRMElev"]
    if not pd.isna(irrmElev):
        irrmStor = elevToStor(irrmElev, resvName)
        seriesIRRM = getIRRMLine(irrmElev, resvName, dfRCStor[resvName])
        #ax.plot(seriesIRRM, ls="dashed", color="tab:red", zorder = 2)
        ax.fill_between(
            seriesIRRM.index, 
            seriesIRRM.values, 
            dfRCStor[resvName], 
            where=(dfRCStor[resvName] >= seriesIRRM.values),      # Only shade where line1 is above line2
            interpolate=True,            # Ensures a clean fill at the intersection points
            color='tab:red',             # Selected soft color from the "Cool" palette
            alpha=0.4,                   # Transparency so background grid is visible
            zorder=1                     # Places the fill behind the boundary lines
        )
        seriesRCClipped = seriesRCClipped.clip(upper=irrmStor)
        ax.text(dfRCStor.index[-2], (dfRCStor[resvName].max()+irrmStor)/2, "Seismic IRRM Pool", ha="right",va="center")
    
    #Conservation Pool
    lowStor = 0
    ax.fill_between(
        dfRCStor[resvName].index, 
        lowStor, 
        seriesRCClipped, 
        interpolate=True,            # Ensures a clean fill at the intersection points
        color='tab:green',             # Selected soft color from the "Cool" palette
        alpha=0.4,                   # Transparency so background grid is visible
        zorder=1                     # Places the fill behind the boundary lines
    )
    ax.text(datetime.datetime(2001,4,15), 0.3*dfRCStor[resvName].max(), "Conservation Pool", ha="center", va="center")
    
    #Min power pool
    minPowerPoolElev = resv_info_dict[resvName]["MinPowerPool"]
    if not pd.isna(minPowerPoolElev):
        minPowerPoolStor = elevToStor(minPowerPoolElev, resvName)
        ax.axhspan(
            lowStor, 
            minPowerPoolStor, 
            color='tab:purple',             # Selected soft color from the "Cool" palette
            alpha=0.4,                   # Transparency so background grid is visible
            zorder=1                     # Places the fill behind the boundary lines
        )
        lowStor = minPowerPoolStor
        ax.text(datetime.datetime(2001,4,15), 0.5*minPowerPoolStor, "Min Power Pool", ha="center", va="center")
    
    #Drawdown pool
    if resvName in dfDrawdownCurves.columns:
        dfDD = dfDrawdownCurves.loc[(dfDrawdownCurves.index >= dfRCStor.index[0]) & 
                                    (dfDrawdownCurves.index <= dfRCStor.index[-1])]
        seriesDD = dfDD[resvName].dropna()
        seriesDD[:] = elevToStor(seriesDD, resvName)
        ax.plot(seriesDD, color="tab:brown", ls = 'dotted', lw=2)
        if resvName == "Lookout Point":
            ax.text(datetime.datetime(2000,10,2), 145, "Deep drawdown", va='top',ha='left',rotation=-73)
            ax.plot([datetime.datetime(2001,3,12),
                     datetime.datetime(2001,4,12),
                     datetime.datetime(2001,4,13)],
                    [spillCrestStor+4, spillCrestStor+4, elevToStor(908, resvName)],
                    color="tab:brown", ls = 'dotted', lw=2)
            ax.text(datetime.datetime(2001,3,13), spillCrestStor+2, "Spill Op", va='top',ha='left',rotation=0)
        if resvName == "Green Peter":
            ax.text(datetime.datetime(2000,10,2), 130, "Deep drawdown", va='top',ha='left',rotation=-73)
        if resvName == "Fall Creek":
            ax.text(datetime.datetime(2000,10,16), 30, "Deep drawdown", va='top',ha='left',rotation=-78)
        if resvName == "Detroit":
            ax.text(datetime.datetime(2000,10,16), 80, "Deep drawdown", va='top',ha='left',rotation=-67)
        if resvName == "Cougar":
            ax.text(datetime.datetime(2000,10,5), 40, "Deep drawdown", va='top',ha='left',rotation=-76)
        if resvName == "Foster":
            ax.text(datetime.datetime(2001,2,10), 2, "Delayed Refill", va='top',ha='left',rotation=0)
    drawdownPoolElev = resv_info_dict[resvName]["DrawdownPool"]
    #if not pd.isna(drawdownPoolElev):
    if 1 == 0:
        drawdownPoolStor = elevToStor(drawdownPoolElev, resvName)
        ax.axhspan(
            lowStor, 
            drawdownPoolStor, 
            color='tab:brown',             # Selected soft color from the "Cool" palette
            alpha=0.4,                   # Transparency so background grid is visible
            zorder=1                     # Places the fill behind the boundary lines
        )
        lowStor = drawdownPoolStor
    
    #Inactive Pool
    #Use "inactive" if defined, otherwise use "min pool", which is lowest outlet invert
    inactivePoolElev = resv_info_dict[resvName]["InactivePool"]
    minPoolElev = resv_info_dict[resvName]["MinElev"]
    minPoolStor = elevToStor(minPoolElev, resvName)
    if not pd.isna(inactivePoolElev):
        minPoolStor = elevToStor(inactivePoolElev, resvName)
        
    ax.axhspan(
        lowStor, 
        minPoolStor, 
        color='tab:orange',             # Selected soft color from the "Cool" palette
        alpha=0.4,                   # Transparency so background grid is visible
        zorder=1                     # Places the fill behind the boundary lines
    )
    ax.text(datetime.datetime(2001,4,15), (lowStor + minPoolStor)/2, "Inactive Pool", ha="center", va="center")
    
    ax.set_ylim([minPoolStor, fullStor])
    ax.grid(True, axis='x', alpha=0.5)
    yAxisStorAtKeyElevs(ax, resvName)
    plt.tight_layout()
    return fig, ax


dfRuleCurves = pd.read_csv(RULECURVE_CSV_FILE, parse_dates=["Date"], index_col="Date")
dfDrawdownCurves = pd.read_csv(DRAWDOWNCURVE_CSV_FILE, parse_dates=["Date Time"], index_col="Date Time")
dfElevStor = pd.read_csv(ELEV_STOR_CSV)
dfReservoirs = pd.read_excel(RESERVOIR_ELEV_XLSX, sheet_name="Reservoirs", header = 5)
resv_info_dict = dfReservoirs.set_index('ReservoirName').to_dict(orient='index') #can call resv_info_dict["Detroit"]["SpillwayCrest"]

dfOneYear = dfRuleCurves.loc[(dfRuleCurves.index >= startDT) & 
                             (dfRuleCurves.index <= endDT)]
#Convert elevation to storage in kaf above min con
dfRCStor = dfOneYear.copy()
for resvName in dfOneYear.columns:
    dfRCStor[resvName] = elevToStor(dfOneYear[resvName], resvName)

if __name__ == "main" or __name__ == "__main__":
    cartoonWCD("Detroit")