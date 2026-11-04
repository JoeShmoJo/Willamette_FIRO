"""
Module with standard conventions for producing output for the FIRO study
This is things like standard order of projects for tables,
as well as standard colors for projects when plotting

This should be referenced by nearly every script that is producing output for powerpoints or the report.
"""


#The standard project order for tables and plot legends
PROJECT_ORDER = ["Hills Creek",
                 "Lookout Point",
                 "Fall Creek",
                 "Dorena",
                 "Cottage Grove",
                 "Cougar",
                 "Blue River",
                 "Fern Ridge",
                 "Green Peter",
                 "Foster",
                 "Detroit"]


#Standard color for each project when plotting them all together
PROJECT_COLOR = {"Hills Creek": 'tab:red',
                 "Lookout Point":'tab:orange',
                 "Fall Creek":'tab:purple',
                 "Dorena":'tab:brown',
                 "Cottage Grove":'tab:pink',
                 "Cougar":'tab:olive',
                 "Blue River":'tab:blue',
                 "Fern Ridge": 'xkcd:marigold',
                 "Green Peter":'tab:green',
                 "Foster":'tab:gray',
                 "Detroit":'tab:cyan',
                 "Lookout Point+Hills Creek":"black" #Sometimes included, not always
                 }



