"""
Create some plots showing the rule curve at all projects on something like the water control diagram (WCD)

Just for testing/playing around

The WCD will start on September 1 so that the winter season remains intact instead of starting on Jan 1
"""

import pandas as pd
import numpy as np
import pickle
from scipy import interpolate
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator, AutoMinorLocator, LinearLocator, PercentFormatter, FuncFormatter, NullFormatter
import datetime

import sys
from pathlib import Path

MODULE_PATH = '../modules'
if not MODULE_PATH in sys.path:
    sys.path.insert(0, MODULE_PATH)

from Utils_Plots import xAxisSeasonal

RULECURVE_CSV_FILE = "../data/common_data/Willamette_Rule_Curves.csv"
ELEV_STOR_CSV = "../data/common_data/ElevStor.csv" 
RESERVOIR_ELEV_XLSX = "../data/common_data/Reservoirs.xlsx" 


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





dfRuleCurves = pd.read_csv(RULECURVE_CSV_FILE, parse_dates=["Date"], index_col="Date")
dfElevStor = pd.read_csv(ELEV_STOR_CSV)
dfReservoirs = pd.read_excel(RESERVOIR_ELEV_XLSX, sheet_name="Reservoirs", header = 5)

startDT = datetime.datetime(2000,9,1)
endDT = datetime.datetime(2001,8,31)

dfOneYear = dfRuleCurves.loc[(dfRuleCurves.index >= startDT) & 
                             (dfRuleCurves.index <= endDT)]

#Convert elevation to storage in kaf above min con
dfRCStor = dfOneYear.copy()
for resvName in dfOneYear.columns:
    dfES = dfElevStor.loc[dfElevStor["Reservoir"]==resvName]
    dfRCStor[resvName] = np.interp(dfOneYear[resvName], dfES["Elev"], dfES["Stor"])
    #Normalize so min conservation pool is 0 storage
    minConElev = dfReservoirs.loc[dfReservoirs["ReservoirName"]==resvName].iloc[0]["MinConElev"]
    minConStor = np.interp(minConElev, dfES["Elev"], dfES["Stor"])
    dfRCStor[resvName] = (dfRCStor[resvName] - minConStor)/1000
    
dfRCPct = dfRCStor/dfRCStor.max()

plt.close('all')
#Spaghetti plot of rule curve storage
fig, ax = plt.subplots()
for i, resvName in enumerate(dfRCStor.max().sort_values(ascending=False).index):
    ax.plot(dfRCStor[resvName], label=resvName, color = color_list[i])
    #Add text label
    ax.text(dfRCStor.index[-1], dfRCStor[resvName].max(), f" {resvName}", ha="left", va="center")
ax.set_xlim([dfRCStor.index[0],dfRCStor.index[-1]])
ax = xAxisSeasonal(ax)
ax.set_ylabel("Rule Curve Storage (kaf)")
plt.tight_layout()


#Same spaghetti plot, but with percent of rule curve storage
fig, ax = plt.subplots()
#for resvName in dfRCPct.loc[datetime.datetime(2001,3,1)].sort_values(ascending=False).index:
#Keep same colors as before
for i, resvName in enumerate(dfRCStor.max().sort_values(ascending=False).index):
    ax.plot(dfRCPct[resvName], label=resvName, color = color_list[i])
    #Add text label
    #ax.text(dfRCPct.index[-1], dfRCPct[resvName].max(), f" {resvName}", ha="left", va="center")
ax.set_xlim([dfRCPct.index[0],dfRCPct.index[-1]])
plt.legend()
ax = xAxisSeasonal(ax)
ax.yaxis.set_major_formatter(PercentFormatter(xmax=1))
ax.set_ylabel("Percent of Rule Curve Storage")
plt.tight_layout()


#Plot up the rule curve
resvName = "Detroit"
fig, ax = plt.subplots(figsize=[5, 4])
ax.plot(dfRCStor[resvName], color='black')
ax = xAxisSeasonal(ax)
ax.set_xlim([dfRCStor.index[0], dfRCStor.index[-1]])
ax.set_ylabel("Rule Curve Storage (kaf)")
fig.suptitle(resvName)
plt.tight_layout()
