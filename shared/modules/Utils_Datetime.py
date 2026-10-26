"""
Utility functions for dealing with dates

@author: Ryan Cahill
""" 
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import norm
import pandas as pd
import matplotlib.ticker as ticker
from matplotlib.ticker import ScalarFormatter, FuncFormatter
import datetime
from datetime import timedelta

################################################################################
# FUNCTION DEFINITIONS

def getWY(datetimeObj):
    year = datetimeObj.year
    if datetimeObj.month>=10:
        return(year+1)
    else:
        return(year)
    
def getWillYr(datetimeObj):
    """
    Returns the "Willamette Year"" of the input, which spans from Aug-July
    So 2011 is Aug 2010-July 2011
    """
    year = datetimeObj.year
    if datetimeObj.month>=8:
        return(year+1)
    else:
        return(year)
    
def getDate2000(datetimeObj):
    ''' returns a datetime object set to water year 2000 (keeps month and day, but resets year)'''
    if datetimeObj.month>=10:
        return(datetime.datetime(1999, datetimeObj.month, datetimeObj.day))
    else:
        return(datetime.datetime(2000, datetimeObj.month, datetimeObj.day))

def getDate2001(datetimeObj, startMonth=10):
    ''' returns a datetime object set to year 2001 (keeps month and day, but resets year)
    If startMonth is set to 10, then it's the water year
    If startMonth is set to 8, then it's the "Wilamette Year" '''
    if datetimeObj.month>=startMonth:
        return(datetime.datetime(2000, datetimeObj.month, datetimeObj.day))
    else:
        return(datetime.datetime(2001, datetimeObj.month, datetimeObj.day))

def getDayInWY(datetimeObj, wy = None, negativeDayLimit=366):
    ''' returns the day number in the WY, where day=1 is October 1.
    If WY is supplied, we'll know that we are going from Oct 1 of this WY, so earlier dates will pop up as negative.
    If the day in the WY is greater than negativeDay Limit, a negative number will be shown.
    This is typically done for dates in August/September, when we want to show them as negative numbers
    instead of as numbers in the high 300's'''
    if wy is None:
        wy = getWY(datetimeObj)
    oct1Date = datetime.datetime(wy-1, 10, 1)
    day_wy = (datetimeObj - oct1Date).days
    if day_wy > negativeDayLimit:
        day_wy = day_wy - 365
    return day_wy

def getDateFromDayInWY(dayInWY):
    '''given a day number, return a date in water year 2000'''
    return datetime.datetime(1999, 10, 1) + timedelta(days=int(dayInWY))
    
def createReadableYearRange(yearList, numDigits=0):
    """
    Takes a list of events, 
    e.g. [1945, 1946, 1947, 1970]
    
    and converts it to a human-readable string with 6 digits for input to ResSim
    e.g. "1945-1947, 1970"
    
    if "numDigits" is supplied, leading zeros will be added
    e.g. "001945-001947, 001970"
    
    """
    years = sorted(yearList)
    outStr = str(years[0]).zfill(numDigits)
    prevYear = years[0]
    inRange = False #running variable to keep track of if we are running up a range like 1945-xxxx
    for i in range(1, len(yearList)):
        prevYear = years[i-1]
        curYear = years[i]
        if curYear == prevYear+1 and i == len(yearList)-1: 
            outStr += "-%s" %str(curYear).zfill(numDigits)
        elif curYear == prevYear+1:
            inRange = True
            continue
        elif curYear > prevYear+1:
            if inRange: 
                #We had been running up a range, need to end that one first
                outStr += "-%s" %str(prevYear).zfill(numDigits)
            outStr += ", %s" %str(curYear).zfill(numDigits)
            inRange = False
    return outStr