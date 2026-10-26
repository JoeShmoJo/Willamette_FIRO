# -*- coding: utf-8 -*-
"""
Contains code dealing with probability distributions that isn't already built-in to python

Note: the pearson3 module behaves differently in Python 3.7 and Python 3.9
In Python 3.7, the distribution is flipped around if skew is negative, which is odd.
This was apparently fixed in 3.9. 
The code here should work for either version of the pearson3 module

@author: Ryan Cahill
"""

import numpy as np
import pandas as pd
from numpy import log10
from scipy.stats import pearson3
from scipy import stats
from scipy.stats import norm, t
from scipy import interpolate

###############################################################################
#CONFIGURATION

################################################################################
# CLASS DEFINITIONS

class QuantileSamplingDist17C:
    """
    This class holds a sampling distribution for a given quantile (e.g. 100-year flow)
    In a method similar to that proposed in Appendix 7 of Bulletin 17C (Equation 7-33)
    Intended to behave like a normal continuous probability distribution,
    where you can call .ppf and .cdf
    But since the Bulletin 17C confidence limits for a given quantile are assymetrical,
    This class is actually a composite of two different distributions based on the T-distribution.
    One for the lower 50%, and one for the upper 50% 
    The two distributions yield the same value at 50% (median)
    Usage:
        Create it based on output from SSP
        Run .findKappas() to set the distribution that fits the SSP sampling distribution
        Then you can use .ppf at will
    """
    def __init__(self, degF, sspComputedCFS, sspVarianceLog, kappaLo=None, kappaHi=None):
        """
        degF = degrees of freedom, typically taken as (number of systematic years - 1)
        kappaLo is typically calculated as the value that creates a match at the 5% confidence limit
        kappaH is typically calculated as the value that creates a match at the 95% confidence limit
        The kappa parameters are usually calculated using 
        """
        self.degF = degF
        self.xMedian = log10(sspComputedCFS)
        self.sigma = np.sqrt(sspVarianceLog)
        self.kappaLo = kappaLo
        self.kappaHi = kappaHi
    def findKappas(self, confLimLowerCFS, confLimUpperCFS, alpha=0.90):
        '''
        alpha = 0.90 means the 90% confidence interval (default in SSP)
        confLimCFS values are sourced straight from the SSP output
        '''
        tLo = t.ppf((1-alpha)/2, self.degF)
        tHi = t.ppf(1 - (1-alpha)/2, self.degF)
        self.kappaLo = (1 - (self.sigma*tLo)/(log10(confLimLowerCFS) - self.xMedian))/tLo
        self.kappaHi = (1 - (self.sigma*tHi)/(log10(confLimUpperCFS) - self.xMedian))/tHi
        return None
    def ppf(self, q):
        ''' input quantile (probability), get value'''
        qArr = np.array(q)
        tVal = t.ppf(q, self.degF)
        #Get different kappas depending on if above/below 0.5
        if qArr.size > 1:
            kappas = np.array([self.kappaLo if qi <=0.5 else self.kappaHi for qi in qArr.tolist()])
        else:
            kappas = self.kappaLo if qArr <=0.5 else self.kappaHi
        xLog = self.xMedian + self.sigma*tVal/(1-kappas*tVal)
        return np.power(10, xLog)
    def cdf(self, x):
        '''input value, get CDF (probability)'''
        raise AssertionError("not implemented yet")

################################################################################
# FUNCTION DEFINITIONS

def LP3Dist(mean, stdDev, skew):
    """
    Nothing special here, just feed in mean, stdDev, skew (of logs) and get the distribution object
    """
    distLP3 = pearson3(loc=mean, scale=stdDev, skew=skew)
    return distLP3

def fitLP3Dist(dataList, method="MLE", floc=None, fskew=None):
    """
    Take a list of datapoints (numbers) and fit an LPIII distribution to it.
    Simple fit based on Maximum Likelihood Estimate as default.
    But Method of Moments is much faster.
    Returns a pearson3 object that you can use to generate random values
    mean is loc
    std dev is scale
    skew is skew
    
    if floc supplied, the mean will be fixed when fitting the distribution
    if fskew supplied, the skew will be fixed when fitting the distribution
    """
    dataLog10 = log10(dataList)
    #MLE
    if method=="MLE":
        if floc is None:
            skew, mean, stdDev = pearson3.fit(dataLog10)
        else:
            skew, mean, stdDev = pearson3.fit(dataLog10, floc=floc, fskew=fskew)
    elif method=="MM":
        #Method of Moments
        skew = stats.skew(dataLog10)
        mean = np.mean(dataLog10)
        stdDev = np.std(dataLog10,ddof=1)
    else:
        raise AssertionError("Method not supported: %s" %method)
    distLP3 = pearson3(loc=mean, scale=stdDev, skew=skew)
    return distLP3

def ppfLP3(distLP3, q):
    """
    In python, the distribution flips around whether skew is positive or negative in python 3.7
    But in Python 3.9, the proper behavior is there.
    But we don't care, if we ask for the 90th percentile, we want that to be the 90th highest!
    Basically a replacement function for ppf.
    Also handles log transform --output is in cfs
    """
    if distLP3.kwds["skew"] >= 0:
        return np.power(10, distLP3.ppf(q))
    else:
        if pearson3(loc=0, scale=1, skew=-0.5).ppf(0.99) > 0: #Correct behavior, Python 3.9
            return np.power(10, distLP3.ppf(q))
        else: #Odd behavior, Python 3.7
            return np.power(10, distLP3.ppf(1-np.array(q)))
        
    
def cdfLP3(distLP3, x):
    """
    In python, the distribution flips around whether skew is positive or negative.
    But we don't care, if we ask for the 90th percentile, we want that to be the 90th highest!
    Basically a replacement function for cdf
    Also handles log transform.
    Input x as flow in cfs
    """
    if distLP3.kwds["skew"] >= 0:
        cdfVal = distLP3.cdf(log10(x))
    else:
        if pearson3(loc=0, scale=1, skew=-0.5).ppf(0.99) > 0: #Correct behavior, Python 3.9
            cdfVal = distLP3.cdf(log10(x))
        else: #Odd behavior, Python 3.7
            cdfVal = 1-distLP3.cdf(log10(x))
    if isinstance(cdfVal, np.ndarray):
        if np.isnan(np.sum(cdfVal)):
            for i in range(len(cdfVal)):
                if np.isnan(cdfVal[i]): 
                    #Happens when skew is really negative and we are checking a large value (or skew is positive and checking a low value)
                    if distLP3.kwds["skew"] <= 0:
                        cdfVal[i] = 1
                    else:
                        cdfVal[i] = 0
    else: #Just a single value
        if np.isnan(cdfVal): 
            #Happens when skew is really negative and we are checking a large value (or skew is positive and checking a low value)
            if distLP3.kwds["skew"] <= 0:
                cdfVal = 1
            else:
                cdfVal = 0
    return cdfVal
def ppfP3(distP3, q):
    """
    Same thing as above, but for regular pearson3 instead of log pearson3
    """
    if distP3.kwds["skew"] >= 0:
        return distP3.ppf(q)
    else:
        if pearson3(loc=0, scale=1, skew=-0.5).ppf(0.99) > 0: #Correct behavior, Python 3.9
            return distP3.ppf(q)
        else: #Odd behavior, Python 3.7
            return distP3.ppf(1-np.array(q))
    
        
def cdfP3(distP3, x):
    """
    Same thing as above, but for regular pearson3 instead of log pearson3
    """
    if distP3.kwds["skew"] >= 0:
        return distP3.cdf(x)
    else:
        if pearson3(loc=0, scale=1, skew=-0.5).ppf(0.99) > 0: #Correct behavior, Python 3.9
            return distP3.cdf(x)
        else: #Odd behavior, Python 3.7
            return 1-distP3.cdf(x) 

def calcExpectedCurve(dfFreqCurves=None, dfFreqCurvesByVal=None, valsToCalculate=None):
    """
    Calculates the "Expected" frequency curve from a set of realization results.
    The "Expected" (or mean) curve must be calculated horizontally (fixed Value, variable AEP),
    not vertically (fixed AEP, variable value).
    Two possible inputs, where each column is a realization. If dfFreqCurves:
        index is z-score
        values are the frequency curve values (typically cfs)
    if dfFreqCurvesByVal (this option is faster):
        index is value (typically cfs)
        values are NEPs
    Returns a dataframe with three columns: zScore, NEP, AEP, and Value
    The output dataframe will be defined at the same index values as the input
    """
    defaultSlices = 50
    dfExpected = pd.DataFrame(columns=["zScore","NEP","AEP","Value"])
    if dfFreqCurves is None:
        df = dfFreqCurvesByVal
    else:
        #Invert the dataframe so that values (cfs) are the index and NEPs in the table
        if valsToCalculate is None:
            #User didn't specify exactly which values to do the calculations at, have to figure it out
            minVal = dfFreqCurves.min().min()
            maxVal = dfFreqCurves.max().max()
            if dfFreqCurves.max().max() > 10000: #Usually if the largest value is above 10,000, we are talking flow and not stage
                valsToCalculate = np.logspace(log10(minVal), log10(maxVal), defaultSlices) #number of values is arbitrary, but should be enough to get definition
            else:
                valsToCalculate = np.linspace(minVal, maxVal, defaultSlices) 
        zScores = dfFreqCurves.index.values
        df = pd.DataFrame(index = valsToCalculate)
        for colName in dfFreqCurves.columns:
            interpObj = interpolate.interp1d(dfFreqCurves[colName], zScores, bounds_error = False, fill_value=(-9, 9))
            df[colName] = norm.cdf(interpObj(valsToCalculate))
    #Calculate the expected probability (just a simple mean)
    seriesMean = df.mean(axis=1)
    if dfFreqCurves is None:
        dfExpected["Value"] = seriesMean.index.values
        dfExpected["NEP"] = seriesMean.values
        dfExpected["zScore"] = norm.ppf(dfExpected["NEP"])
    else:
        dfExpected["zScore"] = dfFreqCurves.index.values
        dfExpected["NEP"] = norm.cdf(dfExpected["zScore"])
        interpObj = interpolate.interp1d(norm.ppf(seriesMean.values), seriesMean.index.values, bounds_error = False, fill_value=(seriesMean.index.min(), seriesMean.index.max()))
        dfExpected["Value"] = interpObj(dfExpected["zScore"])
    dfExpected["AEP"] = 1-dfExpected["NEP"]
    return dfExpected
   
def adjustSkewToMatchVal(matchValCFS, matchAEP, inputMean, inputStdDev, inputSkew, toleranceLog10=0.001, maxIterations=10):
    '''
    Say we have a known LP3 distribution (mean, stddev, skew).
    But we really want it to pass right through a particular value at a particular AEP (matchValCFS at matchAEP)
    This function does this by adjusting the skew parameter until the value is reached.
    A tolerance (in log10) units is to figure when we are close enough
    There is also a maxIterations parameter to prevent it from spinning forever
    This function is intended for use in bias-correction where we are working with
    relatively low AEPS (1% and below), since skew doesn't do much for more common probabilities.
    Assumes that your initial distribution was fairly close to the target to start with.
    This can result in skew values that are not reasonable
    '''
    prob = 1-matchAEP
    matchVal = log10(matchValCFS)
    #Arbitrarily increase/decrease the starting skew guess by a little bit to get iterations going
    skewLo = inputSkew - 0.2
    skewHi = inputSkew + 0.2
    dfTrials = pd.DataFrame(columns=["Skew", "Metric", "Diff", "AbsError"])
    metricLo = ppfP3(pearson3(loc=inputMean, scale=inputStdDev, skew=skewLo), prob)
    metricHi = ppfP3(pearson3(loc=inputMean, scale=inputStdDev, skew=skewHi), prob)
    dfTrials.loc[0] = [skewLo, metricLo, 0, 0]
    dfTrials.loc[1] = [skewHi, metricHi, 0, 0]
    dfTrials["Diff"] = dfTrials["Metric"] - matchVal
    dfTrials["AbsError"] = dfTrials["Diff"].abs()
    for i in range(2, maxIterations):
        #Best guess is an interpolation between the 2 ERL trials with difference just above and below 0
        #When doing the interpolation, use 1/sqrt(erl) rather than just erl, since this is expected to be more linear
        if dfTrials["Diff"].min() < 0 and dfTrials["Diff"].max() > 0:
            #Somewhere between these values
            idxLo = dfTrials.loc[dfTrials["Diff"]<0]["Diff"].idxmax()
            idxHi = dfTrials.loc[dfTrials["Diff"]>0]["Diff"].idxmin()
        else:
            #All the guesses are off on one side, need to extrapolate
            dfBounds = dfTrials.nsmallest(2,"AbsError").sort_values("Diff")
            idxLo = dfBounds.index[0]
            idxHi = dfBounds.index[1]
        x0 = dfTrials.loc[idxLo]["Skew"]
        x1 = dfTrials.loc[idxHi]["Skew"]
        y0 = dfTrials.loc[idxLo]["Diff"]
        y1 = dfTrials.loc[idxHi]["Diff"]
        #A little algebra to try to find the root
        xG = x0 - y0*(x1-x0)/(y1-y0)
        skewTrial = xG 
        metricVal = ppfP3(pearson3(loc=inputMean, scale=inputStdDev, skew=skewTrial), prob)
        diff = metricVal - matchVal
        #if DEBUG: print(erlTrial, metricVal, matchVal, diff, abs(diff))
        dfTrials.loc[i] = [skewTrial, metricVal, diff, abs(diff)]
        if abs(diff) < toleranceLog10:
            #print("Reached tolerance at iteration %s" %(i-1))
            break
    if i == maxIterations-1:
        print("Failed to Converge on skew")
    adjSkew = dfTrials.loc[dfTrials["AbsError"].idxmin()]["Skew"]
    return adjSkew
    
def bootstrapLP3(inputDistLP3, erl, numRealizations=1000, method="MM"):
    '''
    Do a basic parametric bootstrap with a given distribution and erl
    For each realization, draw erl values from the inputDistLP3 and fit a new LP3 distribution
    method="MM" is Method of Moments, "MLE" is Max Likelihood Estimate
    '''
    #dataframe with the bootstrapped LP3 distribution parameters for each realization
    dfBootstrapLP3 = pd.DataFrame(columns=["ERL","Realization","Mean","StdDev","Skew"]) 
    for realizationNum in range(1, numRealizations+1):
        #Bootstrap sample the volume-frequency curve
        #use consistent seed every time we run (but different for each realization)
        dataLog10 = inputDistLP3.rvs(size=erl, random_state=9999999 + realizationNum) #9999 is arbitrary to avoid using the realization number as a seed for other random number generation
        distLP3 = fitLP3Dist(np.power(10,dataLog10), method=method) 
        #dfBootstrapLP3.loc[len(dfBootstrapLP3)+1] = [erl, realizationNum, distLP3.mean(), distLP3.std(), distLP3.kwds["skew"]]
        #For some reason, when skew is 0 or very very close to zero, calling distLP3.mean() fails with a strange ValueError
        #Use kwds instead
        dfBootstrapLP3.loc[len(dfBootstrapLP3)+1] = [erl, realizationNum, distLP3.kwds["loc"], distLP3.kwds["scale"], distLP3.kwds["skew"]]
    return dfBootstrapLP3
    
def _getValAtAEP(x, aep):
    """
    Helper function to returns the value at a given AEP for a given LP3 distribution 
        
    Input is a dictionary object or one row of a dataframe
    Often used with DataFrame.apply() to apply to all rows. 
    """
    val = ppfLP3(LP3Dist(x["Mean"], x["StdDev"], x["Skew"]), 1-aep)
    return val   

def biasCorrectBootstrapLP3(targetSamplingDist17C, targetAEP, dfBootstrapLP3):
    '''
    The uncertainty bounds at a given quantile (e.g. 100-year) are symmetrical
    after doing a normal parametric bootstrap of an LP3 distribution.
    But the "true" sampling distribution (from SSP) for the quantile is not symmetrical.
    This starts with the N realizations of LP3 curves from the "raw" or "naive" bootstrap.
    Then, it adjusts the skew parameters for these curves so that the sampling 
    distribution at the given quantile from the bootstrap matches the target distribution from SSP.
    This should keep the median curve exactly the same, but adjust the uncertainty bounds.
    To do the bias-correction, the CDF of the sampling distribution is used as "anchor" points for the bootstrap.
    In other words, the distribution of 100-year flows from the bootstrap is forced to match the input distribution from SSP.
    '''
    df = dfBootstrapLP3.copy()
    df["OldSkew"] = df["Skew"]
    df["ValStart"] = df.apply(_getValAtAEP, args=(targetAEP, ), axis=1)
    #df["CDF"] = norm.cdf(plot_position(df["ValStart"],a=0,b=0)) #Weibull plotting position
    df["CDF"] = df["ValStart"].rank()/(len(df)+1)
    df["ValTarget"] = targetSamplingDist17C.ppf(df["CDF"])
    newSkews = []
    for i, row in df.iterrows():
        skew = adjustSkewToMatchVal(row["ValTarget"], targetAEP, row["Mean"], row["StdDev"], row["Skew"])
        newSkews.append(skew)
    df["Skew"] = newSkews
    df["ValFinish"] = df.apply(_getValAtAEP, aep=targetAEP, axis=1)
    #The return value doesn't need all the intermediate calculations helpful for debugging
    dfBiasCorrected = dfBootstrapLP3.copy()
    dfBiasCorrected["Skew"] = newSkews
    return dfBiasCorrected
    
def bootstrapWithBiasCorrectionToEMA(numRealizations, erl, biasCorrectAEP, inputMean, inputStdDev, inputSkew, 
                               sspComputedCFS, confLimLowerCFS, confLimUpperCFS, sspVarianceLog, numSystematic):
    '''
    Do a complete bias-corrected parameteric bootstrap for an LP3 distribution.
    Result is a dataframe with the LP3 distribution parameters for each realization.
    
    biasCorrectAEP is the AEP at which we want the bootstrap result to match SSP confidence limits (quantile sampling distribution)
    The following variables need to be supplied at the biasCorrectAEP:
        sspComputedCFS, confLimLowerCFS, confLimUpperCFS, sspVarianceLog
    numSystematic is the number of systematic years from SSP. 
    '''
    inputDistLP3 = LP3Dist(inputMean, inputStdDev, inputSkew)
    dfBootstrapLP3 = bootstrapLP3(inputDistLP3, erl, numRealizations=numRealizations, method="MM")
    degF = numSystematic - 1
    targetSamplingDist17C = QuantileSamplingDist17C(degF, sspComputedCFS, sspVarianceLog)
    targetSamplingDist17C.findKappas(confLimLowerCFS, confLimUpperCFS)
    dfBiasCorrectedLP3 = biasCorrectBootstrapLP3(targetSamplingDist17C, biasCorrectAEP, dfBootstrapLP3)
    return dfBiasCorrectedLP3
    
def demoPlotBootstrapConfDistFitting():
    '''
    #Do a demo plots that shows the reported confidence limits from SSP for the 1000-year event as a CDF
    #Derive a t-distribution that matches these limits
    Rather than creating a bunch of figures, it's intended the user just comments out lines if they aren't desired to be shown
    '''
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MultipleLocator, PercentFormatter, FuncFormatter, NullFormatter
    from Utils_Plots import addLegendAtBottomOfSubplots, ensure_2_major_ticks_log_yaxis, normProbPlot, xAxisSeasonal, plot_position
    from sklearn.neighbors import KernelDensity
    locName = "Hills Creek"
    duration = "5-Day"
    #Got these numbers from SSP by rerunning multiple times with different confidence limits (for the 1000-year event)
    inputMean = 3.764
    inputStdDev = 0.187
    inputSkew = -0.006
    #Confidence intervals from 1000-year event
    sspProbs = [0.005,0.025,0.05,0.15,0.25,0.35,0.4,0.49,0.51,0.6,0.65,0.75,0.85,0.95,0.975,0.995]
    sspVals = [17092.8,17969.4,18473.1,19575.1,20327.9,20990.9,21314.3,21907.6,22044.1,22696,23097.2,24046.2,25392.6,28158.1,29914.1,34250.5]
    sspComputedCFS = 21957
    confLimLowerCFS = 18473.1
    confLimUpperCFS = 28158.1
    sspVarianceLog = 0.0030982
    numSystematic = 107
    erl = 200
    sspZScores = np.array([-2.32634787404084,-1.64485362695147,-1.2815515655446,-0.841621233572914,0,0.841621233572914,1.2815515655446,1.64485362695147,1.75068607125216,2.05374891063182,2.32634787404084,2.5758293035489,2.87816173909548,3.09023230616781,3.29052673149192,3.54008379920617,3.7190164854557,3.89059188641312,4.10747965458601,4.26489079392384,4.4171734134676,4.61138236230822,4.75342430881708])
    ssp05Conf = np.array([1661.2,2437.2,2956,3687.3,5425.7,7803.4,9382.2,10873.3,11339.4,12752.9,14123.4,15460.4,17188.4,18472.2,19740,21396,22636.1,23867.3,25482.7,26697,27905.2,29494.3,30690.9])
    ssp95Conf = np.array([2466.8,3166.1,3648.2,4361.1,6212.3,8951.2,10928.7,12992.8,13686.7,15952,18403.1,21061.7,24931.7,28157.1,31665.5,36782,41050.2,45694.5,52466.8,58114.4,64256.8,73207.9,80667.4])
    sspComputed = np.array([2127.2,2857.6,3343.9,4044.4,5816.1,8358.6,10100.7,11808.4,12357.8,14076,15823.4,17611.1,20048.7,21956.2,23923.2,26621,28739.6,30928.4,33934.2,36296,38736.4,42086.9,44718.5])
    sspExpected = np.array([2039.7,2818.6,3317.8,4028.4,5813.6,8369.1,10127.8,11866.3,12432.3,14221.1,16081.5,18051,20868.5,23211.8,25796,29658.9,32989.8,36763.4,42629,47859.1,53944.5,63704.3,72653.1])
    
    ##########################################################################
    #PLot 1. Show the approximate distribution fit to the SSP sampling distribution for the 1000-year flow
    fig, ax = plt.subplots()
    ax.set_title("Hills Creek 5-Day Unreg, 0.1% AEP (1000-year)")
    #ax.plot(sspVals, sspProbs, color='black', lw=2, label="Sampling Distribution from SSP",marker="o")
    #ax.axhline(0.05,ls='dashed',color='gray')
    #ax.axhline(0.95,ls='dashed',color='gray')
    #ax.text(22000,0.95, "95% limit", va="bottom")
    
    #Refer to Appendix 7 of Bulletin 17C for the equations for the confidence intervals
    df = numSystematic - 1
    t05 = t.ppf(0.05, df)
    x05SSP = log10(confLimLowerCFS)
    t95 = t.ppf(0.95, df)
    x95SSP = log10(confLimUpperCFS)
    x50SSP = log10(sspComputedCFS) #median
    sigma = np.sqrt(sspVarianceLog)
    kappaLo = (1 - (sigma*t05)/(x05SSP - x50SSP))/t05
    kappaHi = (1 - (sigma*t95)/(x95SSP - x50SSP))/t95

    neps = np.arange(0.005,.5,0.005)
    tValsPlot = t.ppf(neps, df)
    xLog = log10(sspComputedCFS) + sigma*tValsPlot/(1-kappaLo*tValsPlot)
    ax.plot(10**(xLog), neps, ls="--", color="tab:orange", label="Approx. Dist (lower), df=%s, k=%0.2f" %(df,kappaLo))
    
    neps = np.arange(0.5,1,0.005)
    tValsPlot = t.ppf(neps, df)
    xLog = log10(sspComputedCFS) + sigma*tValsPlot/(1-kappaHi*tValsPlot)
    ax.plot(10**(xLog), neps, ls="--", color="tab:red", label="Approx. Dist (upper), df=%s, k=%0.2f" %(df,kappaHi))
    
    ax.set_ylabel("CDF")
    ax.set_ylim([0,1])
    ax.set_xlabel("Flow (cfs)")
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=1))
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, p: format(int(x), ',')))
    ax.xaxis.set_minor_formatter(FuncFormatter(lambda x, p: format(int(x), ',')))
    ax.yaxis.set_major_locator(MultipleLocator(0.1))
    ax.legend(loc='lower right')
    
    #Plot 2. Tack on the uncorrected bootstrap to the CDF plot as dots. Put arrows on showing the bias correction process
    numRealizations = 1000
    inputDistLP3 = LP3Dist(inputMean,inputStdDev,inputSkew)
    dfBootstrapLP3 = bootstrapLP3(inputDistLP3, erl, numRealizations, method="MM")
    arr = np.zeros(len(dfBootstrapLP3))
    i=0
    for idx, rowLP3 in dfBootstrapLP3.iterrows():
        arr[i] = ppfLP3(LP3Dist(rowLP3["Mean"], rowLP3["StdDev"], rowLP3["Skew"]), 0.999)
        i+=1
    dfBootstrapLP3["Quantile"] = arr   
    dfBootstrapLP3["zScore"] = plot_position(dfBootstrapLP3["Quantile"],a=0,b=0)
    dfBootstrapLP3["PlotPos"] = norm.cdf(dfBootstrapLP3["zScore"])
    variance = np.var(np.log10(dfBootstrapLP3["Quantile"]),ddof=1)
    ax.scatter(dfBootstrapLP3["Quantile"], dfBootstrapLP3["PlotPos"], s=1, label="Raw Bootstrap (N=%d, ERL=%d)" %(numRealizations, erl), color="tab:blue")
    ax.legend(loc="lower right")
    
    ##########################################################################
    #Plot 3. Show the histogram of bootstrapped skews, before and after bias correction
    dfBiasCorrectedLP3 = bootstrapWithBiasCorrectionToEMA(numRealizations, erl, 0.001, inputMean, inputStdDev, inputSkew, 
                               sspComputedCFS, confLimLowerCFS, confLimUpperCFS, sspVarianceLog, numSystematic)
    #varianceCorrected = np.var(np.log10(dfBiasCorrectedLP3["Quantile"]),ddof=1)
    fig, ax = plt.subplots()
    ax.set_title("Hills Creek 5-Day Unreg, 0.1% AEP (1000-year)")
    kde = KernelDensity(bandwidth=20)
    kde.fit(dfBootstrapLP3["Skew"].to_numpy().reshape(-1,1))
    #pdfKDE = np.exp(kde.score_samples(x.reshape(-1,1)))
    #ax.plot(xDate2000, pdfKDE)
    dfBootstrapLP3["Skew"].plot(ax=ax, kind="kde", color="tab:blue", label="Original Bootstrap")
    dfBiasCorrectedLP3["Skew"].plot(ax=ax, kind="kde", color="tab:green", label="Bias-Corrected Bootstrap")
    ax.axvline(inputSkew, label="Input Skew (SSP)", ls="--", color="gray")
    ax.set_xlim([-1,1])
    ax.yaxis.set_major_formatter(NullFormatter())
    ax.set_yticks([])
    ax.set_ylabel("Probability Density")
    ax.set_xlabel("Skew")
    ax.legend(loc='upper right')
    
    ##########################################################################
    #Plot 4. Show the change in one bootstrap sample from adjusting the skew
    fig, ax = normProbPlot(w=6.5, h=5, lowprob=0.0001, highprob=0.9, logAxis=True)
    aeps = np.logspace(log10(0.9), log10(0.0001), 100)
    neps = 1-aeps
    zScores = norm.ppf(neps)
    rowLP3Raw = dfBootstrapLP3.iloc[1]
    distLP3Raw = pearson3(loc=rowLP3Raw["Mean"], scale=rowLP3Raw["StdDev"], skew=rowLP3Raw["Skew"])
    rowLP3Corrected = dfBiasCorrectedLP3.iloc[1]
    distLP3Corrected = pearson3(loc=rowLP3Corrected["Mean"], scale=rowLP3Corrected["StdDev"], skew=rowLP3Corrected["Skew"])
    ax.plot(norm.ppf(neps), ppfLP3(distLP3Raw, neps), label="Single Bootstrap (1 Realization), skew=%0.2f" %rowLP3Raw["Skew"])
    ax.plot(norm.ppf(neps), ppfLP3(distLP3Corrected, neps), label="Single Bootstrap (1 Realization), bias-corrected skew=%0.2f" %rowLP3Corrected["Skew"])
    ax = ensure_2_major_ticks_log_yaxis(ax)
    ax.set_ylabel("%s volume (cfs)" %duration)
    ax.legend()
    
    ###########################################################################
    #Plot 5. Flow frequency curve uncertainty bounds before/after bootstrap and compare to input
    fig, ax = normProbPlot(w=6.5, h=8.5, lowprob=0.0001, highprob=0.5, logAxis=True)
    ax.set_title("Hills Creek")
    #plt.text(0.97,0.03, locName, ha='right', va = 'bottom', transform = ax.transAxes, size='medium',bbox=dict(facecolor='whitesmoke', edgecolor='dimgray', boxstyle='round'))
    #Add SSP curves
    ax.plot(sspZScores, sspComputed, color="tab:blue", lw=2, label="Input volume-frequency curve (HEC-SSP)", zorder = 3)
    ax.plot(sspZScores, sspExpected, color="tab:blue", ls = "--", label="Expected volume-frequency curve (HEC-SSP)", zorder = 3)
    ax.fill_between(sspZScores, ssp05Conf, ssp95Conf, label="5%/95% confidence limits (HEC-SSP)", color="tab:blue", alpha = 0.2, zorder = 10)
    #Add in the sampled inflow-frequency curves from bootstrapping
    #Add bootstrapped frequency curves
    aeps = np.logspace(log10(0.9), log10(0.0001), 100)
    neps = 1-aeps
    zScores = norm.ppf(neps)
    dfFreqCurveByRealization = pd.DataFrame(index=zScores) #Each column is a realization
    for i, rowLP3 in dfBootstrapLP3.iterrows():
        realizationNum = rowLP3["Realization"]
        distLP3 = pearson3(loc=rowLP3["Mean"], scale=rowLP3["StdDev"], skew=rowLP3["Skew"])
        vals = ppfLP3(distLP3, neps)
        dfFreqCurveByRealization[realizationNum] = vals
    dfFreqCurveByRealization["Expected"] = calcExpectedCurve(dfFreqCurves=dfFreqCurveByRealization)["Value"].values
    dfFreqCurveByRealization["Median"] = dfFreqCurveByRealization.median(axis=1).values
    dfFreqCurveByRealization["LowerConf"] = dfFreqCurveByRealization.quantile(0.05, axis=1).values
    dfFreqCurveByRealization["UpperConf"] = dfFreqCurveByRealization.quantile(0.95, axis=1).values
    ax.plot(zScores,dfFreqCurveByRealization["Median"], ls="-", color="tab:red", linewidth=2, label="Raw Bootstrapped Median", zorder = 1)
    ax.plot(zScores,dfFreqCurveByRealization["LowerConf"], ls=":", color="tab:red", linewidth=2, label="Raw Bootstrapped 5%/95% confidence limits")
    ax.plot(zScores,dfFreqCurveByRealization["UpperConf"], ls=":", color="tab:red", linewidth=2, label=None)   
    ax.plot(zScores,dfFreqCurveByRealization["Expected"], ls="--", color="tab:red", label="Raw Bootstrapped Expected", zorder = 1)
    #Repeat for bias-corrected bootstrap
    for i, rowLP3 in dfBiasCorrectedLP3.iterrows():
        realizationNum = rowLP3["Realization"]
        distLP3 = pearson3(loc=rowLP3["Mean"], scale=rowLP3["StdDev"], skew=rowLP3["Skew"])
        vals = ppfLP3(distLP3, neps)
        dfFreqCurveByRealization[realizationNum] = vals
    dfFreqCurveByRealization["Expected"] = calcExpectedCurve(dfFreqCurves=dfFreqCurveByRealization)["Value"].values
    dfFreqCurveByRealization["Median"] = dfFreqCurveByRealization.median(axis=1).values
    dfFreqCurveByRealization["LowerConf"] = dfFreqCurveByRealization.quantile(0.05, axis=1).values
    dfFreqCurveByRealization["UpperConf"] = dfFreqCurveByRealization.quantile(0.95, axis=1).values
    #ax.plot(zScores,dfFreqCurveByRealization["Median"], ls="-", color="tab:green", linewidth=2, label="Bias-Corrected Bootstrapped Median", zorder = 2)
    #ax.plot(zScores,dfFreqCurveByRealization["LowerConf"], ls=":", color="tab:green", linewidth=2, label="Bias-Corrected Bootstrapped 5%/95% confidence limits")
    #ax.plot(zScores,dfFreqCurveByRealization["UpperConf"], ls=":", color="tab:green", linewidth=2, label=None)   
    #ax.plot(zScores,dfFreqCurveByRealization["Expected"], ls="--", color="tab:green", label="Bias-Corrected Expected", zorder = 2)
    #Deal with axes    
    ax = ensure_2_major_ticks_log_yaxis(ax)
    ax.set_ylim([4000,100000])
    ax.set_ylabel("%s volume (cfs)" %duration)
    ax.legend(loc='upper left')
    plt.tight_layout()
    