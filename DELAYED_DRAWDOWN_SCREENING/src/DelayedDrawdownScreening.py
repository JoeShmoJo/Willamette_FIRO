"""
Do some screening-level analysis on the FIRO Space Component J (delayed fall drawdown)

Below are some messages from Andy Martin to Ryan Cahill on 10/21/2026 on the background here

Fern Ridge benefits irrigation. We're piloting a slower drawdown this year with the help of the Long Tom watershed council and some local irrigators
Short answer is they can leave their pumps and diversions in longer at lower flows
And often we run into the rule curve there in late September
I expect Coast Fork would be just irrigation, but I don't have as strong a case there.
Its just that those are the other reservoirs where we hit the rule curve pretty early
This is such a dry year that we are able to perform the slower Fern Ridge draft without a deviation request, but it's still cutting it close.
I'm ok with looking at how often it would be relevant though, certainly. 
Oh, Fall Creek maybe too.
I'd like to know how often we would have to raise releases at those reservoirs purely because of the rule curve and not because of the drawdown operations. I imagine Fall Creek might happen fairly often. RO flows above 500 cfs / total outflow above 700 cfs negatively impact the adult fish facility.
Right. I believe state water rights for irrigation have an end of season date Oct 31
For FRN, it seems like there are two flows: most irrigation can remain operational at 350 cfs release. 700 cfs cuts off most irrigation ops, but lowers risk of scour and erosion impacting near-channel harvesting equipment 
that 700 is pretty loose. We're not totally sure, but that's what we are going with this year.

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

resvsToPlot = ["Detroit", "Lookout Point", "Fall Creek", "Dorena", "Cottage Grove", "Fern Ridge"]

RULECURVE_CSV_FILE = SHARED_DATA / "common_data/Willamette_Rule_Curves.csv"
RESSIM_OUT_CSV = SHARED_DATA / "ressim_output/2026_10_26/ALL_D.csv.gz"
RESSIM_OUT_CSV_FIRO = SHARED_DATA / "ressim_output/2026_10_26/FALLFIRO.csv.gz"

dfRuleCurves = pd.read_csv(RULECURVE_CSV_FILE, parse_dates=["Date"], index_col="Date")
dfResSim = pd.read_csv(RESSIM_OUT_CSV, parse_dates=["Timestamp"])
#Eliminate leap days
dfResSim = dfResSim.loc[~((dfResSim["Timestamp"].dt.month==2) & (dfResSim["Timestamp"].dt.day==29))].copy()
dfResSim["Date2001"] = dfResSim["Timestamp"].apply(getDate2001, startMonth=8)
dfResSim["WillYr"] = dfResSim["Timestamp"].apply(getWillYr)

#Repeat for simulation with Fall FIRO
#Sloppy, but quick
dfResSimFIRO = pd.read_csv(RESSIM_OUT_CSV_FIRO, parse_dates=["Timestamp"])
dfResSimFIRO = dfResSimFIRO.loc[~((dfResSimFIRO["Timestamp"].dt.month==2) & (dfResSimFIRO["Timestamp"].dt.day==29))].copy()
dfResSimFIRO["Date2001"] = dfResSimFIRO["Timestamp"].apply(getDate2001, startMonth=8)
dfResSimFIRO["WillYr"] = dfResSimFIRO["Timestamp"].apply(getWillYr)

def plotBarChartPctHitRuleCurve():
    #Bar chart showing the percents for each project
    dfPlot = dfPctYrs.loc[dfPctYrs["ResvName"].isin(resvsToPlot)].sort_values("PercentYears")
    fig, ax = plt.subplots()
    ax.barh(dfPlot["ResvName"], dfPlot["PercentYears"])
    ax.set_xlabel("Percent of Years operations constrained by hitting rule curve in fall")
    ax.xaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
    plt.tight_layout()

def plotSpaghettiOnCartoon():
    #Plot up the rule curve as more of a simplified cartoon with zones colored differently
    #For each reservoir separately
    
    # Initialize presentation
    prs = Presentation()
    # Configure 16:9 Widescreen dimensions
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    
    # Use layout 6 (Blank slide) or 5 (Title only)
    blank_layout = prs.slide_layouts[6]
    
    for resvName in resvsToPlot:
    #for resvName in ["Fern Ridge"]:
        fig, ax = cartoonWCD(resvName) #, resv_info_dict, dfRCStor, dfDrawdownCurves)
        
        #Add simulation data as a spaghetti plot
        for yr in range(1936, 2019+1):
            dfOne = dfResSim.loc[dfResSim["WillYr"]==yr]
            ax.plot(dfOne["Date2001"], elevToStor(dfOne[f"{resvName}__Elev"], resvName), color='gray', alpha=0.2)
        
        #Add a highlight showing the rule curve portion of interest
        #31 Oct is end for all reservoirs (end of irrigation season)
        #That's the latest, but may be earlier if deep drawdowns are happening
        startDt = datetime.datetime(2000,9,1)
        if resvName=="Fern Ridge":
            startDt = datetime.datetime(2000,9,20)
        
        endDt = datetime.datetime(2000,10,31)
        if resvName in endMonthDict:
            endDt = datetime.datetime(2000,endMonthDict[resvName],30)
        seriesRCLimit = dfRuleCurves[resvName].loc[(dfRuleCurves.index>=startDt) &(dfRuleCurves.index <=endDt)]
        
        seriesRCLimit.loc[:] = elevToStor(seriesRCLimit.values, resvName)
        ax.plot(seriesRCLimit, color="tab:red", lw=5)
        
        #Push to powerpoint
        # Save to memory buffer
        image_stream = io.BytesIO()
        fig.savefig(image_stream, format="png", bbox_inches="tight")
        image_stream.seek(0)
        #plt.close(fig)  # Free memory
    
        # Add slide and insert image
        slide = prs.slides.add_slide(blank_layout)
        
        # Position: left, top, width (height auto-scales to maintain aspect ratio)
        left = Inches(2.66)
        top = Inches(1.5)
        width = Inches(8.0)
        
        #slide.shapes.add_picture(image_stream, left, top, width=width)
        
        slide.shapes.add_picture(
            image_stream,
            left=0,
            top=0,
            width=prs.slide_width,
            height=prs.slide_height
        )
    
    # Save final deck
    prs.save(OUTPUT_DIRECTORY / "DelayedFallDrawdown.pptx")

def histogramUneven(data_points):
    
    # 2. Define your bin boundaries and nice labels
    # We use a value slightly below zero (-1e-9) to ensure that exact 0s are correctly
    # grouped into the 'Zero' category when 'right=True' is used.
    bins = [-1e-9, 0, 10, 25, np.inf]
    labels = ['0', '0-10', '10-25', '25+']
    
    # 3. Categorize the data into custom bins
    df = pd.DataFrame({'values': data_points})
    df['bin'] = pd.cut(df['values'], bins=bins, labels=labels, right=True)
    
    # 4. Count the frequencies for each bin category
    bin_counts = df['bin'].value_counts().reindex(labels)
    
    # 5. Plot the result as a bar chart (which behaves as our custom histogram)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(bin_counts.index, bin_counts.values/len(df), color='skyblue', edgecolor='black', width=0.6)
    
    
    # Formatting the plot
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
    plt.title('Fall Creek Fall FIRO', fontsize=14, fontweight='bold', pad=15)
    #ax.set_xlabel('Increased number of days below 700 cfs', fontsize=12, labelpad=10)
    ax.set_xlabel('Extra number of days pumps are available (<700 cfs)', fontsize=12, labelpad=10)
    ax.set_ylabel('Percent of years', fontsize=12, labelpad=10)
    ax.grid(axis='y', linestyle='--', alpha=0.7)

##############################################################################
#Main Code

#Calculate the percent of years where we run into rule curve between 01Sep and Oct 31
endMonthDict = {"Detroit":9, "Green Peter":9, "Lookout Point":9}
dfMerge = pd.merge(dfResSim, dfRuleCurves, how="inner", left_on="Timestamp", right_index=True)
dataList = []
for resvName in resvsToPlot:
    endMonth = 10
    if resvName in endMonthDict:
        endMonth = endMonthDict[resvName]
    df = dfMerge.loc[(dfMerge["Timestamp"].dt.month>=9) & (dfMerge["Timestamp"].dt.month<=endMonth)].copy()
    df["ElevAbvRC"] = df[f"{resvName}__Elev"] - df[resvName]
    seriesMaxDiff = df[["WillYr","ElevAbvRC"]].groupby("WillYr").max()
    pctYrs = len(seriesMaxDiff.loc[seriesMaxDiff["ElevAbvRC"]>=-1])/len(seriesMaxDiff)
    dataList.append([resvName, pctYrs])
dfPctYrs = pd.DataFrame(columns=["ResvName", "PercentYears"], data=dataList)

plt.close('all')

plotBarChartPctHitRuleCurve()

plotSpaghettiOnCartoon()

#Count up number of days greater than 700 cfs at Fall Creek in the fall
dfMerge = pd.merge(dfResSim, dfResSimFIRO, how="inner", on="Timestamp", suffixes=["","_FIRO"])
for resvName in ["Fall Creek"]:
    endMonth = 10
    if resvName in endMonthDict:
        endMonth = endMonthDict[resvName]
    df = dfMerge.loc[(dfMerge["Timestamp"].dt.month>=9) & (dfMerge["Timestamp"].dt.month<=endMonth)].copy()
    seriesNumBadDays = df.loc[df[f"Fall Creek__Flow-OUT"] > 701].groupby("WillYr")[f"Fall Creek__Flow-OUT"].count()
    seriesNumBadDaysFIRO = df.loc[df[f"Fall Creek__Flow-OUT_FIRO"] > 701].groupby("WillYr")[f"Fall Creek__Flow-OUT_FIRO"].count()
    dfBadDays = pd.DataFrame(index=np.arange(1935, 2020))
    dfBadDays["Base"] = seriesNumBadDays
    dfBadDays["FIRO"] = seriesNumBadDaysFIRO
    dfBadDays = dfBadDays.fillna(0)
    #dfBadDays = pd.merge(seriesNumBadDays, seriesNumBadDaysFIRO, how='outer', left_index=True, right_index=True)
    dfBadDays["NumDaysBetter"] = dfBadDays["Base"] - dfBadDays["FIRO"] 
histogramUneven(dfBadDays["NumDaysBetter"])

#Basic spaghetti of FAL
fig, ax = plt.subplots()
series = dfResSim[f"Fall Creek__Flow-OUT"]
for yr in range(1936, 2019+1):
    dfOne = dfResSim.loc[dfResSim["WillYr"]==yr]
    ax.plot(dfOne["Date2001"], dfOne[f"Fall Creek__Flow-OUT"], color='gray', alpha=0.2)
    
