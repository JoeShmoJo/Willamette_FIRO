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

import sys
from pathlib import Path

MODULE_PATH = '../modules'
if not MODULE_PATH in sys.path:
    sys.path.insert(0, MODULE_PATH)

from Utils_Plots import xAxisSeasonal
from ProbabilityDistributions import LP3Dist, ppfLP3, cdfLP3
from Utils_Datetime import getDate2001, getWillYr

RULECURVE_CSV_FILE = "../data/common_data/Willamette_Rule_Curves.csv"
DRAWDOWNCURVE_CSV_FILE = "../data/common_data/Drawdown_Target_Curves.csv"
ELEV_STOR_CSV = "../data/common_data/ElevStor.csv" 
RESERVOIR_ELEV_XLSX = "../data/common_data/Reservoirs.xlsx" 
RESSIM_OUT_CSV = "../data/ressim_output/2026_10_26/ALL_D.csv.gz"
RESSIM_OUT_CSV_FIRO = "../data/ressim_output/2026_10_26/FALLFIRO.csv.gz"

# A list of 11 distinct colors using Tableau 10 and a complementary XKCD color
color_list = [
    'tab:blue',
    'tab:orange',
    'tab:green',
    'tab:red',
    'tab:purple',
    'tab:brown',
    'tab:pink',
    'tab:gray',
    'tab:olive',
    'tab:cyan',
    'xkcd:marigold'  # 11th color: highly distinct gold/yellow
]


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

def cartoonWCD(resvName, resv_info_dict, dfRCStor, dfDrawdownCurves):
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


startDT = datetime.datetime(2000,8,1)
endDT = datetime.datetime(2001,7,31)

dfOneYear = dfRuleCurves.loc[(dfRuleCurves.index >= startDT) & 
                             (dfRuleCurves.index <= endDT)]

#Convert elevation to storage in kaf above min con
dfRCStor = dfOneYear.copy()
for resvName in dfOneYear.columns:
    dfRCStor[resvName] = elevToStor(dfOneYear[resvName], resvName)
    
dfRCPct = dfRCStor/dfRCStor.max()


#Calculate the percent of years where we run into rule curve between 01Sep and Oct 31
endMonthDict = {"Detroit":9, "Green Peter":9, "Lookout Point":9}
dfMerge = pd.merge(dfResSim, dfRuleCurves, how="inner", left_on="Timestamp", right_index=True)
dataList = []
for resvName in dfReservoirs["ReservoirName"]:
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

#Bar chart showing the percents for each project
resvsToPlot = ["Detroit", "Lookout Point", "Fall Creek", "Dorena", "Cottage Grove", "Fern Ridge"]
dfPlot = dfPctYrs.loc[dfPctYrs["ResvName"].isin(resvsToPlot)].sort_values("PercentYears")
fig, ax = plt.subplots()
ax.barh(dfPlot["ResvName"], dfPlot["PercentYears"])
ax.set_xlabel("Percent of Years operations constrained by hitting rule curve in fall")
ax.xaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
plt.tight_layout()



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
    fig, ax = cartoonWCD(resvName, resv_info_dict, dfRCStor, dfDrawdownCurves)
    
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
    seriesRCLimit = dfRCStor[resvName].loc[(dfRCStor.index>=startDt) &(dfRCStor.index <=endDt)]
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
prs.save("../out/DelayedFallDrawdown.pptx")
    

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
    ax.set_xlabel('Increased number of days below 700 cfs', fontsize=12, labelpad=10)
    ax.set_ylabel('Percent of years', fontsize=12, labelpad=10)
    ax.grid(axis='y', linestyle='--', alpha=0.7)


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
    
