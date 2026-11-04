"""
Script to compute regression equations to predict the unregulated volume
from a given date through 30-Sep 
based on unregulated inflow volume for the 30-days prior.

30-days prior seemed to give the best correlation (better than 15 or 60 days)
Still not as good as an actual forecast, but this is information that is
readily available to ResSim, so it serves as a proxy for an actual forecast

This information is used by the ResSim logic that determines if we are draining
reservoirs too fast and need to cut flows down.

The CSV file produced by this script is intended to be placed directly in ResSim
and read by the rules/state variables there. 

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
from scipy import stats
import matplotlib.pyplot as plt
import datetime

from Output_Conventions import PROJECT_COLOR
from Utils_Plots import xAxisSeasonal


#################################
#User input
UNREG_CSV = SHARED_DATA / "datasets_sharepoint/EIS_Unreg.csv"

OUT_CSV = OUTPUT_DIRECTORY / "ResidualVolumeRegressions.csv"

#Locations to process
RESV_LIST = ["Hills Creek", "Lookout Point", "Fall Creek", "Cottage Grove", "Dorena",
             "Cougar", "Blue River", "Fern Ridge", "Green Peter", "Detroit"]
#RESV_LIST = ["Detroit"]
##################################

# Load and clean the CSV data
df_clean = pd.read_csv(UNREG_CSV, skiprows=4)
df_clean['Date'] = pd.to_datetime(df_clean['Date'], format='%d%b%Y')
df_clean['Year'] = df_clean['Date'].dt.year

df_clean = df_clean.sort_values('Date').reset_index(drop=True)
df_clean.set_index('Date', inplace=True, drop=False)

years = sorted(df_clean['Year'].unique())
dates_range = pd.date_range('2020-04-01', '2020-09-30')
num_dates_to_process = len(dates_range)
md_list = [(d.month, d.day) for d in dates_range]


# Conversion factor: cfs-day to thousand Acre-Feet (KAF)
CFSD_TO_KAF = 86400 / 43560 / 1000

dfs = []
for locName in RESV_LIST:
    print(locName)
    #Extract antecedent volumes (30 days) and target volumes (to Sep 30) for each day
    print("Extracting antecedent volumes")
    daily_datasets = {i: [] for i in range(num_dates_to_process)}
    for yr in years:
        year_data = df_clean[df_clean['Year'] == yr]
        season_data_yr = year_data[(year_data['Date'].dt.month >= 4) & (year_data['Date'].dt.month <= 9)]
        if len(season_data_yr) != num_dates_to_process:
            continue
        
        march_data = year_data[year_data['Date'].dt.month == 3]
        if len(march_data) < 30:
            continue
            
        start_date = pd.to_datetime(f"{yr}-03-01")
        end_date = pd.to_datetime(f"{yr}-09-30")
        seq_data = df_clean.loc[start_date:end_date]
        
        dates_yr = pd.date_range(f"{yr}-04-01", f"{yr}-09-30")
        flows_series = seq_data[locName] * CFSD_TO_KAF
        
        for idx, d_yr in enumerate(dates_yr):
            pred_start = d_yr - pd.Timedelta(days=30)
            pred_end = d_yr - pd.Timedelta(days=1)
            pred_vol = flows_series.loc[pred_start:pred_end].sum()
            target_vol = flows_series.loc[d_yr:pd.to_datetime(f"{yr}-09-30")].sum()
            
            daily_datasets[idx].append((pred_vol, target_vol))
    
    # 3. Fit independent regressions and compute stats
    print("Fitting Regressions")
    raw_regressions = []
    for idx in range(183):
        data = daily_datasets[idx]
        if len(data) < 50:
            continue
        X = np.array([x[0] for x in data])
        Y = np.array([x[1] for x in data])
        
        slope, intercept, r_value, p_value, std_err = stats.linregress(X, Y)
        
        n = len(X)
        x_mean = np.mean(X)
        y_pred = slope * X + intercept
        residuals = Y - y_pred
        s_err = np.sqrt(np.sum(residuals**2) / (n - 2))
        r2 = r_value**2
        
        # 95% PI margin of error evaluated at the mean of X
        t_val = stats.t.ppf(0.975, df=n-2)
        pi_95 = t_val * s_err * np.sqrt(1 + 1/n)
        
        # Extract the historic minimum inflow volume for that given date
        min_inflow_vol = np.min(Y)
        
        raw_regressions.append({
            'DayIndex': idx,
            'slope': slope,
            'intercept': intercept,
            'std_err': s_err,
            'R2': r2,
            'Min_Vol': min_inflow_vol
        })
    
    df_raw = pd.DataFrame(raw_regressions)
    
    # 4. Adjust slope/intercept to make sure that the regressino lines don't cross
    # from one day to another 
    df_raw['slope_adj'] = df_raw['slope']
    df_raw['intercept_adj'] = df_raw['intercept']
    
    for i in range(1, len(df_raw)):
        if df_raw.loc[i, 'slope_adj'] > df_raw.loc[i-1, 'slope_adj']:
            df_raw.loc[i, 'slope_adj'] = df_raw.loc[i-1, 'slope_adj']
        if df_raw.loc[i, 'intercept_adj'] > df_raw.loc[i-1, 'intercept_adj']:
            df_raw.loc[i, 'intercept_adj'] = df_raw.loc[i-1, 'intercept_adj']
    
    # 5. Format and Export DataFrame
    month_map = {4: 'Apr', 5: 'May', 6: 'Jun', 7: 'Jul', 8: 'Aug', 9: 'Sep'}
    df_raw['Location'] = locName
    df_raw['Month'] = [md_list[i][0] for i in range(num_dates_to_process)]
    df_raw['Day'] = [md_list[i][1] for i in range(num_dates_to_process)]
    df_raw['Month_Name'] = df_raw['Month'].map(month_map)
    df_raw['Date'] = df_raw.apply(lambda r: f"{int(r['Day']):02d}-{r['Month_Name']}", axis=1)
    
    df_report = df_raw[['Location', 'Month', 'Day', 'intercept_adj', 'slope_adj', 'std_err', 'R2', 'Min_Vol']].rename(
        columns={'intercept_adj': 'Intercept', 'slope_adj': 'Slope', 'std_err':'Std_Err'}
    )
    
    dfs.append(df_report)

# Combine all locations
df_final_report = pd.concat(dfs, ignore_index=True)

#Write to CSV
#df_final_report.to_csv(OUT_CSV, index=False)
timestampToday = datetime.datetime.today().strftime("%Y-%m-%d")
header_lines = [
    "# Residual Volume regressions\n",
    "# Date Created: %s\n" %timestampToday,
    "# Input to regressions are previous 30 day unregulated volume (kaf)\n",
    "# Output is a prediction of the remaining unregulated volume from the given date to 30-Sep (kaf)\n",
    "# Produced by external script on git repo\n",
    "#\n"
    ]

# Open the file and write both the headers and the DataFrame
with open(OUT_CSV, mode='w', encoding='utf-8', newline='') as f:
    f.writelines(header_lines)   # Write the metadata rows
    df_final_report.to_csv(f, index=False)

def plotRegressionStrengthAllProjects(df_final_report):
    """
    Simple plot with date on x, r2 on the y
    Separate line for each project
    """
    dfPlot = df_final_report[["Location","Month","Day","R2"]].copy()
    dfPlot["Date"] = [datetime.datetime(2001, m, d) for m, d in zip(dfPlot["Month"],dfPlot["Day"])]
    
    fig, ax = plt.subplots()
    for resvName in RESV_LIST:
        color = PROJECT_COLOR[resvName]
        df = dfPlot.loc[dfPlot["Location"]==resvName]
        ax.plot(df["Date"], df["R2"], label=resvName)
    ax = xAxisSeasonal(ax)
    ax.set_ylabel("R squared of regression fit")
    ax.legend()
    return fig, ax
    

def plotExampleRegression():
    """
    Example regression with prediction interval
    """
    locName = "Detroit"
    
    regression_data_june = []
    
    for yr, group in df_clean.groupby('Year'):
        # Predictor: May Inflow Volume (31 days)
        prev_30_data = group[group['Date'].dt.month == 5]
        if len(prev_30_data) != 31:
            continue
        prev_30_vol = prev_30_data[locName].sum() * CFSD_TO_KAF
        
        # Target: June-September Inflow Volume (122 days)
        target_data = group[(group['Date'].dt.month >= 6) & (group['Date'].dt.month <= 9)]
        if len(target_data) != 122:
            continue
        target_vol = target_data[locName].sum() * CFSD_TO_KAF
        
        regression_data_june.append({
            'Year': yr,
            'Target_Vol': target_vol,
            'Prev_30_Vol': prev_30_vol
        })
    
    df_reg = pd.DataFrame(regression_data_june)
    
    # 2. Extract arrays
    X = df_reg['Prev_30_Vol'].values
    Y = df_reg['Target_Vol'].values
    n = len(X)
    
    # Fit linear regression
    slope, intercept, r_value, p_value, std_err = stats.linregress(X, Y)
    
    # 3. Compute 95% Prediction Intervals (PI)
    x_mean = np.mean(X)
    sum_sq_x = np.sum((X - x_mean)**2)
    
    # Residuals and residual standard error (s_err)
    y_pred = slope * X + intercept
    residuals = Y - y_pred
    s_err = np.sqrt(np.sum(residuals**2) / (n - 2))
    
    # Two-tailed t-value for 95% confidence (alpha = 0.05, degrees of freedom = n-2)
    t_val = stats.t.ppf(1 - 0.05 / 2, df=n - 2)
    
    # Generate fine sequence of X for smooth plotting of bands
    x_seq = np.linspace(X.min() - 10, X.max() + 10, 200)
    y_seq = slope * x_seq + intercept
    
    # Standard Error of Prediction (includes "+ 1" term for individual prediction interval)
    pred_se = s_err * np.sqrt(1 + 1/n + (x_seq - x_mean)**2 / sum_sq_x)
    pi_half_width = t_val * pred_se
    
    pi_lower = y_seq - pi_half_width
    pi_upper = y_seq + pi_half_width
    
    # 4. Plotting
    fig, ax = plt.subplots(figsize=(9, 6.5))
    ax.scatter(X, Y, color='blue', alpha=0.7, edgecolors='k', zorder=3, label='Historical Years (1936-2018)')
    ax.plot(x_seq, y_seq, color='red', linewidth=2.5, zorder=4, label=f'Best Fit Line (R² = {r_value**2:.3f})')
    ax.fill_between(x_seq, pi_lower, pi_upper, color='red', alpha=0.15, zorder=2, label='95% Prediction Interval (PI)')
    
    # Labels and styling
    ax.set_xlabel('Antecedent 30-Day Volume (May) [KAF]', fontsize=11)
    ax.set_ylabel('Remaining Seasonal Volume (June-Sep) [KAF]', fontsize=11)
    ax.set_title('Detroit Dam: June–September Inflow Volume Forecast\nwith 95% Prediction Interval (May Predictor)', fontsize=12, fontweight='bold')
    ax.grid(True, linestyle='--', alpha=0.5)
    
    # Add Equation statistics as text box
    #eq_text = f"June-Sep Vol = {slope:.4f} * May_Vol + {intercept:.2f}\nResidual Std Error = {s_err:.2f} KAF"
    #ax.text(0.05, 0.92, eq_text, transform=ax.transAxes, fontsize=10, bbox=dict(facecolor='white', alpha=0.8, boxstyle='round,pad=0.5'))
    
    ax.legend(loc='lower right', fontsize=10)
    plt.tight_layout()
    plt.show()
    return fig, ax


#Create plots
plt.close('all')
plotRegressionStrengthAllProjects(df_final_report)  
plt.savefig(OUTPUT_DIRECTORY / "RegressionStrengthAllLocations.png")
plotExampleRegression()
plt.savefig(OUTPUT_DIRECTORY / "ExampleRegressionDetroitJune.png")