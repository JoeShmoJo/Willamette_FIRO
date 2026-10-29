# MAX FIRO Space

This workflow uses two Python scripts to estimate available Forecast-Informed Reservoir Operations (FIRO) space at downstream control points and identify reservoir-level constraints. The analysis combines unregulated flow data, NOAA rating curves, selected flood events, reservoir storage-elevation relationships, evacuation assumptions, and reservoir-to-control-point routing alternatives.

config: 

	space_limits_config.xlsx : configuration workbook. Contains control point information, selected flood events, reservoir information, and reservoir-to-control-point routing alternatives

data: contains required input datasets

	ResvLagTimes_Median.csv — Lag times from each reservoir to downstream control points
	storage_elevation.xlsx — Storage-elevation rating tables for each reservoir
	OutputLocalUnreg.dss — HEC-DSS file containing unregulated flow data. This file is not included in the repository because of its size.

out: contains analysis outputs

	BankfullValues.csv — Bankfull stages and calculated bankfull flows for each control point
	EventVolume.pkl — Event-level available FIRO space and event-magnitude results by control point
	ControlPointsSpace.csv — Estimated available FIRO space limit at each downstream control point for the selected probability of exceedance
	ReservoirEvacLimits.csv — Estimated seven-day evacuation volume for each reservoir
	ReservoirLimitingFactors.csv — Summary of limiting factors for each reservoir, including normal evacuation capability and downstream control-point space constraints
	

src: contains the python scripts

	find_events.py — Reads hourly unregulated flow data from an HEC-DSS file and retrieves NOAA rating tables for each configured control point. It converts configured bankfull stages to bankfull flows, identifies times when flows exceed bankfull, and calculates the available volume during the lead time preceding each selected event. Available FIRO space is calculated as the difference between channel volume at bankfull flow and actual flow volume during the lead-time window. The script produces bankfull-flow tables and an event-volume dataset containing available FIRO space and event-magnitude values for each control point.

	size_space_components.py — Uses the event-volume dataset to fit a Pearson Type III distribution of available FIRO space at each control point. A user-defined probability-of-exceedance value is used to establish a downstream space limit. The script also calculates conservation storage from reservoir storage-elevation curves and estimates the volume that can be evacuated in seven days based on the configured time required to evacuate 20 percent of conservation storage. It then distributes downstream space among upstream reservoirs in proportion to conservation storage for each configured routing alternative. The final output identifies the factors that most constrain available space for each reservoir.