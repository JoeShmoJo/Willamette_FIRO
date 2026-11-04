"""
Basic plots showing example ops at Detroit in WY 2015 with min flow cuts in place

Ryan Cahill
2026-11-04

Junk that can be deleted, just used to make some plots for sharing

"""

import pandas as pd
import numpy as np
import pickle
from scipy import interpolate
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator, AutoMinorLocator, FixedLocator, LinearLocator, FormatStrFormatter, PercentFormatter, FuncFormatter, NullFormatter
from scipy.stats import norm
import datetime
import io
from pptx import Presentation
from pptx.util import Inches
from datetime import timedelta

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

from Utils_Plots import xAxisSeasonal
from ProbabilityDistributions import LP3Dist, ppfLP3, cdfLP3
from Utils_Datetime import getDate2001, getWillYr
from WCD_Cartoon_Plots import cartoonWCD, elevToStor

##############################################################################
#USER INPUTS

RESSIM_DIR = SHARED_DATA / "ressim_output/2026_11_04"

CSV_Dict = {"Meet Full Demand": "FIRO_Base_NoMinFlowCuts_2015.gz",
            "With Cuts": "FIRO_Base_2015.gz",
#            "With FIRO": "FIRO_Test.gz",
            "Observed": "DET_OBS.csv"
            }

resvsToPlot = ["Detroit"]

RULECURVE_CSV_FILE = SHARED_DATA / "common_data/Willamette_Rule_Curves.csv"

startDate =datetime.datetime(2000,10,1)
endDate = datetime.datetime(2001,9,30)


def plotElevsOnCartoon():
    #Plot up the rule curve as more of a simplified cartoon with zones colored differently
    #For each reservoir separately
    
    for resvName in resvsToPlot:
    #for resvName in ["Fern Ridge"]:
        fig, ax = cartoonWCD(resvName,
                             startDT=startDate,
                             endDT=endDate)
        for altName, dfResSim in dfResSimDict.items():
            startDt2000 = datetime.datetime(2000, dfResSim["Timestamp"].iloc[0].month, dfResSim["Timestamp"].iloc[0].day)
            xValues = pd.date_range(startDt2000, startDt2000+timedelta(days=len(dfResSim)-1))
            ax.plot(xValues, elevToStor(dfResSim[f"{resvName}__Elev"], resvName), label=altName)
        ax.legend()

def plotReleases():   
    for resvName in resvsToPlot:
    #for resvName in ["Fern Ridge"]:
        fig, ax = plt.subplots()
        for altName, dfResSim in dfResSimDict.items():
            ax.plot(dfResSim["Timestamp"], dfResSim[f"{resvName}__Flow-OUT"], label=altName)
        ax = xAxisSeasonal(ax)
        ax.set_ylabel("Detroit Release (cfs)")
        ax.set_xlim([datetime.datetime(2015,3,1), datetime.datetime(2015,9,30)])
        ax.set_ylim([0,2000])
        ax.legend()

def plotSalem():   
    
    for locName in ["Salem"]:
        fig, ax = plt.subplots()
        for altName, dfResSim in dfResSimDict.items():
            ax.plot(dfResSim["Timestamp"], dfResSim[f"{locName}__Flow"], label=altName)
        ax = xAxisSeasonal(ax)
        ax.set_ylabel("Salem Flow (cfs)")
        ax.set_xlim([datetime.datetime(2015,3,1), datetime.datetime(2015,9,30)])
        ax.set_ylim([0,20000])
        ax.legend()

##############################################################################
#Main Code

#Calculate the percent of years where we run into rule curve between 01Sep and Oct 31
dfRuleCurves = pd.read_csv(RULECURVE_CSV_FILE, parse_dates=["Date"], index_col="Date")

dfResSimDict = {}
for altName, csvName in CSV_Dict.items():
    dfResSim = pd.read_csv(RESSIM_DIR / csvName, parse_dates=["Timestamp"])
    #Eliminate leap days
    dfResSim = dfResSim.loc[~((dfResSim["Timestamp"].dt.month==2) & (dfResSim["Timestamp"].dt.day==29))].copy()
    dfResSim["Date2001"] = dfResSim["Timestamp"].apply(getDate2001, startMonth=8)
    dfResSim["WillYr"] = dfResSim["Timestamp"].apply(getWillYr)
    dfResSimDict[altName] = dfResSim
plt.close('all')

plotElevsOnCartoon()

plotReleases()

#plotSalem()

    
