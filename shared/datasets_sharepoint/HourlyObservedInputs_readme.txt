

HourlyObservedInputs.dss

Currently used in the lag time/routing/evacuation task. TODO needs to be changed.

Sourced from Willamette flow-frequency link here:
..\1.8_RoutingParameters\data


-Took the "USGS_Hourly.dss" file and put it into this file. Renamed f-part to "BEST" and cleared out A-Part.
-Also took all of the post-flood report hydrographs and put them in here. Sourced from here:
../1.3_GageData-Corrected\Digitization_QC\data\PostFloodDigitized.dss
-This file is the master working dataset with all true "observed" data to be used for the routing study.
-This file is read by the python script to do the Modified Puls routing simulations. 
-Renamed "Detroit", "Lookout Point" records for "Flow-OUT" to "Big Cliff" and "Dexter"
-Made sure all reservoir release had a c-part of "FLOW-OUT", like Green Peter
-Filled in short periods of missing data via interpolation for some sites:
Feb 1996: Jefferson, McMinnville
Nov 1996: Aurora, Waterloo
Dec 1998: Harrisburg, Salem
Jan 2006: Goshen, Fern Ridge, Waterloo, Dilley, Aurora, West Linn
Jan 2012: Vida, Mehama
Apr 2019: Coburg, Corvallis, Big Cliff, Newberg, Aurora
-Filled in the Oregon City stage records using the Lower Columbia data submittal from USGS (LCR_RawDataset.dss).
-Took an outdated rating table at Oregon City from NWRFC and applied it. It is way off at low flows, but kind of decent for high flows.
-On 2022-01-28, added in more digitized hydrographs from Dec 1955 and Dec 1964 from USGS water supply paper tables.