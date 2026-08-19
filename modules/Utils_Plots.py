"""
Utility functions for plotting data

Things like axis manipulation etc.

Originally developed by Trey Crouch for Lower Columbia River Stage Frequency
Modified for this project

function normProbPlot() -> for processing and plotting frequency figures  
with return period (top of plot)and Percent Annual Exceedance Probability (bottom) as x-ax, 
    
""" 

import numpy as np
from numpy import log10
import matplotlib.pyplot as plt
from scipy.stats import norm
import matplotlib.dates as mdates
import pandas as pd
import matplotlib.ticker as ticker
from matplotlib.ticker import ScalarFormatter, FuncFormatter

################################################################################
# FUNCTION DEFINITIONS

def strAEP(aep):
    '''
    returns a nicely formatted string representing the AEP. 
    Input for 100-year is 0.01, output is "1%"
    Input for 1000-year is 0.01, output is "0.1%"
    '''
    if aep < 0.001:
        a = round(aep*100,2)
    elif aep < 0.01:
        a = round(aep*100,1)
    elif aep < 1:
        a = int(round(aep*100,0))
    aepStr = "%s%%" %a
    return aepStr

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
    
def ensure_2_major_ticks_log_yaxis(ax):
    '''
    Sometimes only one single tick mark at a order of magnitude is shown (e.g. only 10,000 cfs)
    If this happens, make sure we plot at least two
    '''
    yticks = ax.get_yticks()
    yLim = ax.get_ylim()
    numTicksShown = 0
    for ytick in yticks:
        if yLim[0] <= ytick < yLim[1]:
            numTicksShown += 1
    if numTicksShown <= 1:
        pass
        #Need to add more
        #Find the tick that is closes to the the current axis limits
        yNewPt = 0
        minDiff = 999999999999
        for ytick in yticks:
            if yLim[0] <= ytick < yLim[1]: continue #Already included, skip this one
            diff = min(abs(log10(ytick) - log10(yLim[0])),abs(log10(ytick) - log10(yLim[1])))
            if diff < minDiff:
                yNewPt = ytick
                minDiff = diff
        yMinNew = min(yNewPt, yLim[0])
        yMaxNew = max(yNewPt, yLim[1])
        ax.set_ylim([yMinNew, yMaxNew])
    return ax
    
def addLegendAtBottomOfSubplots(fig, ax, numThumbnails, ncol=2):
    '''
    Often, we have subplots that each have exactly the same legend
    This function takes the legend from one of the thumbnails and puts it at the 
    bottom of the figure
    Assumes we are working with a 3x2 grid of thumbnails
    
    Intended to be applied after all subplots have been created
    '''
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc='lower center', ncol=ncol)
    plt.tight_layout()
    if numThumbnails <= 2:
        plt.subplots_adjust(bottom=0.4)
    elif numThumbnails <= 4:
        plt.subplots_adjust(bottom=0.2)
    else:
        plt.subplots_adjust(bottom=0.18)
    return fig, ax
    
def normProbPlot(title='Default', w=6.5, h=4.25, lowprob=0.0001,highprob=0.9,logAxis=True, fig=None, ax=None, 
    returnPeriodAEPs=[0.50, 0.20, 0.10, 0.02, 0.01, 0.002, 0.0001, 0.000001],
    returnPeriodLabel = 'Average Return Interval (years)'):
    """
    This functions returned a shell for creating probability exceedance plots  
    
    :param  title:  What you want the title to be. 
    :param  w:  width of the plot (inches)
    :param  h:  height of the plot (inches)
    :param  low:            decimal low probability, for maximum plot extent flexibility -this has to be in decimal not percent
    :param  high:           decimal high probability, for plot extent flexibility -this has to be in decimal not percent    
    :param fig: if provided, the plot will be added to existing figure
    :param ax: if provided, the plot will be added to existing axes
    :param returnPeriodAEPs: if provided, this is a list of AEPs for which return periods will be shown. Otherwise, defaults will be used
                            e.g. [0.5, 0.2, 0.1]
    :return fig and axes defined with specified format ready to add data
    """
    if ax is None:
        fig, ax = plt.subplots(figsize=(w,h)) #this is for portrait orientation
    #Label axes
    ax.set_xlabel('Annual Exceedance Probability (%)')
    ax.set_ylabel('Annual Maximum Flow (cfs)')
    #Title at upper left, inside plot 
    #plt.text(0.5,1.08, title, ha='center', fontsize=20, transform = ax.transAxes)
    if title != 'Default':
        ax.text(0.03,0.97, title, ha='left', va = 'top', transform = ax.transAxes, size='medium',bbox=dict(facecolor='whitesmoke', edgecolor='dimgray', boxstyle='round'))
    ax.set_axisbelow(True) #makes the grid lines show up behind everything else
    ax.grid() #adds grid
    #Primary y-axis
    if logAxis:
        ax.set_yscale("log")
        #ax.yaxis.set_major_formatter(ScalarFormatter())
        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, p: format(int(x), ',')))
        #ax.yaxis.set_minor_formatter(FuncFormatter(lambda x, p: format(int(x), ',')))
        ax.yaxis.grid(which="minor", color='#999999', linestyle='-', alpha=0.2)
    #Primary x-axis labels - Percent Annual Exceedance Probability
    prob = np.array([0.90, 0.50, 0.10, 0.01, 0.001, 0.0001, 0.00001])
    probStr = ["90","50","10","1","0.1","0.01", "0.001"]
    #prob_percent = np.multiply(prob,100)
    normprob_ticks = -norm.ppf(prob)  #calculates the inverse of standard normal cumulative distribution function for desired axis labels
    #plt.xticks(normprob_ticks,prob_percent.astype(str)) # set tick locations
    #plt.xticks(normprob_ticks,probStr) # set tick locations
    ax.set_xticks(normprob_ticks,probStr) # set tick locations
    # define the minor grid lines 
    prob_minor = np.array([0.90, 0.80, 0.70, 0.60, 0.50, 0.40, 0.30, 0.20, 0.10, 
        0.09, 0.08, 0.07, 0.06, 0.05, 0.04, 0.03, 0.02, 0.01, 
        0.009, 0.008, 0.007, 0.006, 0.005, 0.004, 0.003, 0.002, 0.001,
        0.0009, 0.0008, 0.0007, 0.0006, 0.0005, 0.0004, 0.0003, 0.0002, 0.0001,
        0.00009, 0.00008, 0.00007, 0.00006, 0.00005, 0.00004, 0.00003, 0.00002, 0.00001])
    normprob_minticks = -norm.ppf(prob_minor)
    #Show minor gridlines with very faint and almost transparent grey lines
    ax.xaxis.set_minor_locator(ticker.FixedLocator(normprob_minticks))
    ax.grid(visible=True, which='minor', axis = 'x',color='#999999', linestyle='-', alpha=0.2)
    #Set limits based on specified decimal high and low annual exceedance probability
    ax.set_xlim([-norm.ppf(highprob),-norm.ppf(lowprob)])
    #ax.set_ylim([10,50])
    
    #Secondary x-axis labels - Return period (years)
    #Adds return intervals labels on the top x-axis
    ax2=ax.twiny() #secondary axis
    prob2 = np.array(returnPeriodAEPs) #secondary ax ticks (return period)
    normprob_ticks2 = -norm.ppf(prob2)
    ax2.set_xticks(normprob_ticks2) #setting secondary axis tick marks
    #ax.tick_params(which='both',axis='both', direction='in') # This might look nicer, but would have to space axe layer further out
    ax2.tick_params(axis='x', direction='in')
    ax2.set_xbound(ax.get_xbound())
    ax2Xs = [] #creating blank array for secondary axis tick marks
    for X in prob2: #calculating return period from percent annual Exceedance proba
        ax2Xs.append(int(1/X))
    ax2.set_xticklabels(ax2Xs)
    ax2.set_xlabel(returnPeriodLabel)
    return fig, ax #matplotlib.axes object that we can add data

def plot_position(data, a = 0.3, b = 0.3):
    """
    This function takes the input data (should be a list or 1-d numpy array)
        and calculates the plotting position zScores based on 
        the number of peak values. 
    param: data: is an array of values for the period of interest. Can be in any order (doesn't have to be sorted)
    param: a, b: specifies which method to use for plotting positions.
        Default plotting position is Median
        User can specify plotting position via a and b variables.
        Plotting position calculated using formula:
        (m-A)/(n+1-A-B)
        m=Rank
        n=Number of Years
        A,B = Constants
        Weibull: A and B = 0
        Median: A and B = 0.3
    """
    numEvents = len(data)
    ##Calc z-scores for the plot of all sampled events. 
    rank = np.array(data).argsort().argsort() + 1
    plotPos = (rank - a)/(numEvents + 1 - a - b) 
    zScores = norm.ppf(plotPos)
    return zScores
