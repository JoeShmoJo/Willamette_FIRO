# -*- coding: utf-8 -*-
"""
FIRO_SPACE (aka FILL_FIRO_SPACE)
Scripted rule that steers the pool toward a FIRO space rule curve that is read
from an external CSV instead of being defined as a zone in ResSim.

How it works
------------
initRuleScript (once per compute):
    Reads a generic-year (no year, just Month/Day) daily elevation CSV and builds
    a piecewise-linear curve of day-of-year -> FIRO_SPACE elevation for this
    reservoir. Also grabs the reservoir's elevation-storage table.

runRuleScript (every timestep):
    Looks up the FIRO_SPACE elevation for this step, converts it to storage, and
    computes the release that would land the pool exactly on that storage at the
    end of the current timestep:

        qTarget = inflow + (storPrev - targetStor) / cfsToAcFt

    Then it sets a MAXIMUM limit 

    The result is "hold the pool at or below FIRO_SPACE".
    
    The other wrinkle here is that a "soft minimum" flow can optionally be supplied
    alt config variable name: firoFallSoftMinFlow
    
    When this "soft min" supplied, we will not drop our max release below this level to fill FIRO space.
    This is used in the fall when we don't really want to fill into the FIRO space,
    but we are OK with doing it if it allows us to keep releases below a threshold level.
    e.g. spawning flow limit or flow at which irrigation pumps get wet.
    This same concept could be used if we wanted to try to make sure we don't drop below
    critical fish flows in the winter/spring to fill FIRO space, but that is not implemented yet.
    It's not really a "minimum flow", but a minimum limit on the max flow.

    The limit is a CONTINUOUS function of the storage error: as the pool
    approaches the curve, qTarget approaches inflow. There is deliberately no
    "rule does not bind" branch. An earlier version returned 0 when the
    pool was near the curve, which handed control back to the rest of the stack
    the instant the target was met and produced a hard one-day-period
    oscillation -- the pool floated up off the curve, got slammed back down, and
    repeated. Do not reintroduce a discontinuity here.

    This rule only proposes the target. Other rules in the stack are expected to
    constrain the release further (outlet capacity, min flows, ramp rates, etc.).


    The MAXIMUM release by design competes with
    minimum-flow rules. Stack placement matters. 
    Should be pretty low in the stack, but higher priority than "Draft To Rule Curve".
    Lower priority than things like deep drawdowns, minimum flows, FIRO pre-release, etc.

Config CSV format (wide, one row per day of a generic year):
    Month,Day,Detroit,Hills Creek,Lookout Point,...
    1,1,1450.0,1448.0,825.0,...
    1,2,1450.0,,825.1,...

    A day has a target only where that day's cell holds a number. A BLANK cell
    means NO TARGET on that day: the rule returns a limit that does not bind and
    the rest of the stack operates the project. So you can leave whole stretches
    of the year uncontrolled just by clearing those cells.

    Column headers are matched to ResSim reservoir names ignoring surrounding
    whitespace and letter case, so a stray space after a name in the header does
    not silently hide the column.

    A reservoir with no numbers at all -- a column of blanks, or no column --
    is simply never controlled. That is not an error, so one config file can
    serve a whole watershed while only some projects use the rule. Set
    REQUIRE_RESERVOIR_IN_CONFIG to True to make it an error instead.

    Lines starting with # are comments. A "Notes" column is ignored.

    Targets are held in a 365-entry per-day lookup table rather than an
    Interpolate object, because "this day has no target" is not something a
    continuous interpolation can express.

Sub-daily timesteps
    Each day's value is the target at the end of that day (2400). A daily run
    uses it as is. A sub-daily run (e.g. 3-hour) interpolates between the
    previous day's value and today's by time of day, so the target moves
    smoothly instead of jumping once a day. See getTargetElev. The first step
    of every compute prints its time and target to the compute log, so you can
    confirm the rule is seeing the time of day.

Author: Josh Roach
"""

from hec.rss.model import OpValue
from hec.rss.model import OpRule
from hec.heclib.util import HecTime

from NWDJyLib.cFile import fileOpenReadClose, stripOutCommentLines, \
    getCSVDictReader, convertCSVDictReaderToListDict
from NWDJyLib.cTimes import getHecTimeFromRuntimestep
from NWDJyLib.ResSim.cResSim import getElevationStorageTable

################################################################################
# USER INPUT

# alt_config key holding the path to the config CSV.
CONFIG_KEY = "firoSpaceConfigCSV"

# Spread the storage correction over this many days rather than demanding the
# whole thing in one timestep. This is the gain of the controller. 0 asks the
# pool to land exactly on the curve every step, which can be jumpy when the rest of
# the stack cannot deliver the requested release. DraftToRC.py uses 3 days.
# This must be less than or equal to the GLIDE_DAYS in DraftToRC.py, otherwise this rule
# will cause the pool to draft slower after a flood than it would in a non-FIRO alternative, 
# which doesn't make sense
GLIDE_DAYS = 0 #Just snap it back, let the draft to RC rule handle the smoothing

# Bridge a run of undefined days this long or shorter by interpolating between
# the numbers on either side. 0 means never bridge, so every blank day is an
# uncontrolled day -- the usual choice for a full 365-row daily file. Set it to
# 365 to specify a project with a handful of breakpoints and let the rule
# interpolate the rest of the year, the way a ResSim zone would.
INTERPOLATE_GAPS_UP_TO_DAYS = 0

# False: a reservoir with no numbers in the config is simply never controlled,
# and the compute continues. True: that is a hard error that stops the compute.
REQUIRE_RESERVOIR_IN_CONFIG = False

# Set True to print target elevation / release to the ResSim compute log each step
DEBUG = False

################################################################################
# CONSTANTS
CFSDAY_TO_AF = (60 * 60 * 24) / 43560.0  # multiply a daily cfs by this to get ac-ft (~1.98)

# Column headers in the config CSV that are not reservoir names
NON_RESERVOIR_COLUMNS = ["MONTH", "DAY", "NOTES", ""]

DAYS_IN_YEAR = 365

################################################################################
# FUNCTION DEFINITIONS


def _ok(v):
    """Return float(v) if it is usable, or None if it is missing/NaN/a DSS sentinel."""
    try:
        f = float(v)
    except:
        return None
    # NaN is the only value not equal to itself. Avoids needing math.isnan.
    if f != f:
        return None
    # HEC/DSS missing-value sentinels are around 1e38
    if abs(f) > 1e30:
        return None
    return f


def _getResvName(currentRule):
    """Reservoir name as ResSim knows it, e.g. "Lookout Point" (not "LOP")."""
    resvElement = currentRule.getReservoirElement()
    try:
        return resvElement._name
    except:
        return resvElement.toString()


def _genericDayOfYear(hTime):
    """
    Day of year (Jan 1 = 1) for the given date, projected onto a non-leap year.

    Projecting onto 2001 first matters: calling dayOfYear() directly on a real
    leap-year date shifts everything after Feb 28 by one day relative to the
    generic-year curve. Feb 29 is treated as Feb 28.
    """
    month = hTime.month()
    day = hTime.day()
    if month == 2 and day == 29:
        day = 28
    probe = HecTime()
    probe.setYearMonthDay(2001, month, day, 1440)  # 1440 = 2400 hours
    return int(probe.dayOfYear())


def _findColumnForReservoir(resvName, columnNames):
    """
    Match a ResSim reservoir name to a config column, tolerating a stray space
    or a difference in capitalization. Returns the column name, or None.
    """
    for col in columnNames:
        if col == resvName:
            return col
    wanted = resvName.strip().upper()
    for col in columnNames:
        if col.strip().upper() == wanted:
            return col
    return None


def _readCell(cell):
    """
    Interpret one cell: a float if it holds a number, or None for a blank cell,
    which means no target that day. Raises for anything else, so a typo in an
    elevation is caught rather than silently turning into an uncontrolled day.
    """
    if cell is None:
        return None
    text = str(cell).strip()
    if text == "":
        return None
    return float(text)   # an error here is caught by the caller


def _buildDayTable(dayElevDict):
    """
    Turn {dayOfYear: elevation} into a 365-entry lookup table, indexed 1..365,
    holding a float on days with a target and None on days without one.
    Runs of undefined days up to INTERPOLATE_GAPS_UP_TO_DAYS long are filled in
    by interpolating between the numbers on either side, wrapping across 31Dec.
    """
    table = [None] * (DAYS_IN_YEAR + 1)   # index 0 is unused
    definedDays = list(dayElevDict.keys())
    definedDays.sort()
    if not definedDays:
        return table
    for day in definedDays:
        table[day] = dayElevDict[day]
    if INTERPOLATE_GAPS_UP_TO_DAYS <= 0:
        return table
    for i in range(len(definedDays)):
        startDay = definedDays[i]
        endDay = definedDays[(i + 1) % len(definedDays)]
        gap = endDay - startDay
        if gap <= 0:
            gap += DAYS_IN_YEAR   # wraps past 31Dec, or the only breakpoint
        numMissing = gap - 1
        if numMissing <= 0 or numMissing > INTERPOLATE_GAPS_UP_TO_DAYS:
            continue
        elevStart = dayElevDict[startDay]
        elevEnd = dayElevDict[endDay]
        for k in range(1, gap):
            day = startDay + k
            if day > DAYS_IN_YEAR:
                day -= DAYS_IN_YEAR
            table[day] = elevStart + (elevEnd - elevStart) * (float(k) / gap)
    return table


def countTargetDays(dayTable):
    """How many days of the year this reservoir actually has a target."""
    total = 0
    for day in range(1, DAYS_IN_YEAR + 1):
        if dayTable[day] is not None:
            total += 1
    return total


def loadFiroConfig(configCSV):
    """
    Read the FIRO_SPACE config CSV.

    :param str configCSV: full path to the config CSV
    :return: {columnName: 365-entry day table} for every reservoir column found,
             including columns that turn out to be entirely blank
    :rtype: dict
    """
    lines = fileOpenReadClose(configCSV)
    lines = stripOutCommentLines(lines)
    csvDict = getCSVDictReader(lines)
    csvListDict = convertCSVDictReaderToListDict(csvDict)

    # .fieldnames is only populated after iterating, which the line above did
    fieldNames = []
    for f in list(csvDict.fieldnames):
        if f is not None:
            fieldNames.append(f)
    resvNames = []
    for f in fieldNames:
        if f.strip().upper() not in NON_RESERVOIR_COLUMNS:
            resvNames.append(f)
    if not resvNames:
        raise AssertionError(
            "No reservoir columns found in %s. Expected headers like "
            "'Month,Day,Detroit,Hills Creek,...'\nHeaders actually read: %s"
            % (configCSV, ", ".join([repr(f) for f in fieldNames])))

    breakpoints = {}
    for resvName in resvNames:
        breakpoints[resvName] = {}
    for rowNum, rowDict in enumerate(csvListDict):
        try:
            month = int(rowDict["Month"])
            day = int(rowDict["Day"])
        except:
            raise AssertionError(
                "Bad or missing Month/Day on data row %d of %s"
                % (rowNum + 1, configCSV))
        hTime = HecTime()
        hTime.setYearMonthDay(2001, month, day, 1440)  # 2001 is a non-leap year
        dayOfYear = hTime.dayOfYear()
        for resvName in resvNames:
            try:
                elev = _readCell(rowDict.get(resvName))
            except:
                raise AssertionError(
                    "Could not read '%s' as an elevation for %s on row %d of %s. "
                    "Use a number, or leave the cell blank to mean no target "
                    "that day."
                    % (rowDict.get(resvName), resvName, rowNum + 1, configCSV))
            if elev is None:
                continue
            if dayOfYear in breakpoints[resvName]:
                raise AssertionError(
                    "Duplicate entry for %s on month %d day %d in %s"
                    % (resvName, month, day, configCSV))
            breakpoints[resvName][dayOfYear] = elev

    firoCurves = {}
    for resvName in resvNames:
        firoCurves[resvName] = _buildDayTable(breakpoints[resvName])
    return firoCurves


def getTargetElev(dayTable, hTime):
    """
    FIRO_SPACE elevation for the given time, or None if there is no target
    that day and the rule should leave the project alone.

    Each day's value is the target at the end of that day (2400). A sub-daily
    step interpolates between the previous day's value and today's by the
    time of day, so a 3-hour run follows the curve instead of stepping once a
    day, which could carry the target across a rule curve it runs close to.
    A daily step lands at 2400 and gets the day's value, as before.
    """
    doy = _genericDayOfYear(hTime)
    today = dayTable[doy]
    minutes = hTime.hour() * 60 + hTime.minute()
    if today is None or minutes <= 0 or minutes >= 1440:
        return today
    before = dayTable[doy - 1 if doy > 1 else 365]
    if before is None:
        return today
    return before + (today - before) * (minutes / 1440.0)


def _resolveConfigPath(network):
    """Full path to the config CSV: the alt_config entry, or the default."""
    # Scripted rules may also initialize before state variables do.
    altSetupSV = network.getStateVariable("Alternative_Setup")
    configFromAlt = altSetupSV.varGet(CONFIG_KEY)
    if configFromAlt:
        configCSV = configFromAlt
    else:
        raise AssertionError("Could not locate config variable from Alternative Setup: %s" %CONFIG_KEY)
    return network.makeAbsolutePathFromWatershed(configCSV)


def _fmtElev(elev):
    """Format an elevation for the log, showing days with no target plainly."""
    if elev is None:
        return "no target"
    return "%.2f" % elev


def _initialize(currentRule, network):
    """
    Read the config CSV and stash everything this rule needs on the rule object.
    Called from initRuleScript, once per compute.
    """
    altSetupSV = network.getStateVariable("Alternative_Setup")
    if not altSetupSV.varGet("firoActive"):
        currentRule.varPut("firoActive", False)
        return None
    currentRule.varPut("firoActive", True)

    resvName = _getResvName(currentRule)
    #Pick up the soft minimum if it exists
    softMinFall = 0
    firoFallSoftMinFlows = altSetupSV.varGet("firoFallSoftMinFlows")
    if resvName in firoFallSoftMinFlows:
        softMinFall = firoFallSoftMinFlows[resvName]
    csvFileName = _resolveConfigPath(network)
    firoCurves = loadFiroConfig(csvFileName)

    columnNames = list(firoCurves.keys())
    columnNames.sort()
    column = _findColumnForReservoir(resvName, columnNames)
    dayTable = None
    if column is not None:
        dayTable = firoCurves[column]
    numTargetDays = 0
    if dayTable is not None:
        numTargetDays = countTargetDays(dayTable)

    if numTargetDays == 0:
        # No curve for this project. Not an error by default: the rule simply
        # never controls, so one config file can serve a whole watershed.
        message = (
            "FIRO_SPACE: %s has no target elevations in %s, so this rule will "
            "not control it. Columns in that file: %s"
            % (resvName, csvFileName, ", ".join(columnNames)))
        if REQUIRE_RESERVOIR_IN_CONFIG:
            raise AssertionError(message)
        network.printMessage(message)
        dayTable = [None] * (DAYS_IN_YEAR + 1)

    currentRule.varPut("softMinFall", softMinFall)
    currentRule.varPut("firoCurve", dayTable)
    currentRule.varPut("elevStorTable", getElevationStorageTable(resvName, network))
    currentRule.varPut("stepsLogged", 0)

    if numTargetDays > 0:
        # One line per load, so the compute log always shows which numbers are
        # in play. If an edited CSV is not being picked up, this is where it
        # shows. Days without a target are reported so a stretch of blanks that
        # was not intended is obvious.
        janOne = dayTable[1]
        julOne = dayTable[182]
        network.printMessage(
            "FIRO_SPACE: loaded %s from column '%s', %d of %d days have a "
            "target (%d uncontrolled), 01Jan=%s 01Jul=%s, from %s"
            % (resvName, column, numTargetDays, DAYS_IN_YEAR,
               DAYS_IN_YEAR - numTargetDays,
               _fmtElev(janOne), _fmtElev(julOne), csvFileName))
    return dayTable


# Steps printed to the compute log at the start of every compute. On a
# sub-daily run the time of day should advance and the target should change
# a little every step. If every step prints 2400, the rule is not getting the
# time of day, and the target will step once a day.
STEPS_TO_LOG = 3


def _logFirstSteps(currentRule, network, currentRuntimestep, resvName, hTime,
                   targetElev):
    """Print the first few steps' time and target, once per compute."""
    logged = currentRule.varGet("stepsLogged")
    if logged is None or logged >= STEPS_TO_LOG:
        return
    currentRule.varPut("stepsLogged", logged + 1)
    network.printMessage(
        "FIRO_SPACE %s: step of %d min at %s (hour %d, minute %d), target %s"
        % (resvName, currentRuntimestep.getTimeStepMinutes(),
           hTime.dateAndTime(), hTime.hour(), hTime.minute(),
           _fmtElev(targetElev)))


def initRuleScript(currentRule, network):
    """
    Runs at the start of every compute, so an edited CSV is picked up at the
    next compute. The file is not checked again while the compute runs: a
    check on every call was a large share of compute time.
    """
    _initialize(currentRule, network)
    return True


def runRuleScript(currentRule, network, currentRuntimestep):
    """Runs every timestep of the compute."""
    if not currentRule.varGet("firoActive"):
        return None
    opValue = OpValue()
    resvName = _getResvName(currentRule)
    firoCurve = currentRule.varGet("firoCurve")
    elevStorTable = currentRule.varGet("elevStorTable")

    # Today's target, as elevation and as storage. A day with no target means
    # the rule stands down and lets the rest of the stack operate the project.
    hTime = getHecTimeFromRuntimestep(currentRuntimestep)
    targetElev = getTargetElev(firoCurve, hTime)
    #_logFirstSteps(currentRule, network, currentRuntimestep, resvName, hTime, targetElev)
    if targetElev is None:
        if DEBUG:
            network.printMessage(
                "FIRO_SPACE %s %s: no target today, not controlling"
                % (resvName, hTime.dateAndTime()))
        opValue.init(OpRule.RULETYPE_MIN, 0.0)
        return opValue
    targetStor = elevStorTable.interpolate(targetElev)

    # Pool state at the end of the previous timestep, and this timestep's inflow
    elevPrev = _ok(network.getTimeSeries(
        "Reservoir", resvName, "Pool", "Elev").getPreviousValue(currentRuntimestep))
    storPrev = _ok(network.getTimeSeries(
        "Reservoir", resvName, "Pool", "Stor").getPreviousValue(currentRuntimestep))
    inflow = _ok(network.getTimeSeries(
        "Reservoir", resvName, "Pool", "Flow-IN").getCurrentValue(currentRuntimestep))

    # Release that walks the pool onto the target over GLIDE_DAYS. At
    # GLIDE_DAYS = 0 this lands exactly on the target in a single timestep.
    timeStepMinutes = currentRuntimestep.getTimeStepMinutes()
    cfsToAcFt = CFSDAY_TO_AF * timeStepMinutes / 1440.0
    stepsInGlide = GLIDE_DAYS * 1440.0 / timeStepMinutes
    if stepsInGlide < 1.0:
        stepsInGlide = 1.0
    qTarget = inflow + (storPrev - targetStor) / (cfsToAcFt * stepsInGlide)
    qTarget = max(qTarget, 0.0)

    #Account for "soft minimum" limit in the fall
    softMinFall = currentRule.varGet("softMinFall")
    if hTime.month() in [8,9,10]:
        qTarget = max(qTarget, softMinFall)

    qTarget = max(qTarget, 0.0)
    # qTarget equals inflow exactly when
    # the pool is on the curve, is above inflow when high, below inflow when low.
    opValue.init(OpRule.RULETYPE_MAX, qTarget)

    if DEBUG:
        network.printMessage(
            "FIRO_SPACE %s %s: targetElev=%.2f elevPrev=%.2f inflow=%.0f release=%.0f"
            % (resvName, hTime.dateAndTime(), targetElev, elevPrev, inflow,
               qTarget))

    return opValue


# RTS initialization adapter; original runRuleScript above remains unchanged.
_rts_baseline_direct = True
_rts_original_initRuleScript = initRuleScript

def initRuleScript(currentRule, network):
    import sys
    scripts = str(network.makeAbsolutePathFromWatershed("scripts"))
    if scripts not in sys.path:
        sys.path.append(scripts)
    from standalone_baseline_runtime import initialize_rule
    return initialize_rule("FIRO_SPACE", currentRule, network, globals())
