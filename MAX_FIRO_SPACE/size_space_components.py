# -*- coding: utf-8 -*-
"""
Created on Thu Oct 15 16:08:43 2026

@author: g2echsfb
"""
# BEGIN COMMENTED FIRO WORK: earlier component geometry
# Retained for review. Active A/C/E/H/I/J/K geometry is in FIRO_COMPONENTS/src/02_build_component_curves.py.
# import pandas as pd
# import numpy as np
# import pickle
# from find_events import read_DSS_data, read_all_pathnames, load_data_dict
# from space_limits import find_conservation_storage, calculate_7_day_evacuation_volume, summary_of_alternatives
# from space_limits import distribute_downstream_space, calculate_limiting_space
# import matplotlib.pyplot as plt
# import matplotlib.dates as mdates
#
#
# ######## config
# PROJECT_DATA  = r'../data/project_data.csv'
# STOR_ELEV = r"../data/storage_elevation.xlsx"
# RULE_CURVES = r'../data/Willamette_Rule_Curves.dss'
# RULE_CURVES_PICKLE = r'../data/willamette_rule_curves.pkl'
# CONTROL_POINT_SPACE =r'../data/control_points_space.csv'
#
# REUPLOAD_RULE_CURVE = False
#
# ########### Funtions
#
# def clean_rule_curves(rule_curves):
#     '''
#     Restrict each project's rule curve to a single 12-month period,
#     beginning in August and ending the following July.
#     '''
#     start = "2018-08-01" # random year
#     end = "2019-07-31"
#     for project, df in rule_curves.items():
#         rule_curves[project] = df.loc[start:end]
#
# def find_FIRO_space_E(project_data, rule_curves, stor_elev):
#     """
#     Estimate the number of days FIRO storage space can be used above the
#     project rule curve before the rule curve reaches the refill elevation.
#
#     For each project, the function:
#     1. Converts the maximum control elevation (MaxCon) to storage using
#        the project's storage-elevation rating curve.
#     2. Subtracts the allocated FIRO storage space (FIROSpaceKAF) from
#        the maximum control storage to determine the target storage.
#     3. Converts the target storage back to elevation.
#     4. Searches the rule curve between StartRefill and HitRefill to find
#        when the rule curve crosses the target elevation.
#     5. Calculates the number of days between this crossing date and
#        HitRefill, representing the duration that FIRO space can be used
#        above the rule curve.
#     """
#     FIRO_space_E = {}
#     for row in project_data.itertuples():
#         project = row.Project
#         # Retrieve the project's storage-elevation rating curve.
#         rating = stor_elev[stor_elev['Project'] == project]
#         # Convert the maximum control elevation to storage.
#         storage_max_con = np.interp(row.MaxCon, rating['Elevation (ft)'], rating['Storage_KAF'])
#         # Subtract  FIRO space to determine the target storage.
#         target_storage = storage_max_con - row.FIROSpaceKAF
#         target_elevation = np.interp(target_storage, rating['Storage_KAF'], rating['Elevation (ft)'])
#         rule_curve = rule_curves[project.upper()] # get rule curve
#         # Restrict the rule curve to the refill period
#         refill_season = rule_curve.loc[row.StartRefill:row.HitRefill]
#
#         # Calculate the difference between the rule curve and target elevation.
#         # A sign change indicates that the target elevation has been crossed.
#         s = refill_season['value'] - target_elevation
#         # Identify the first interval containing a crossing.
#         i = np.where(s.iloc[:-1].values * s.iloc[1:].values <= 0)[0][0]
#         # Linearly interpolate to estimate the date of the crossing.
#         target_date = (s.index[i] - pd.Timedelta(days=s.iloc[i] / (s.iloc[i + 1] - s.iloc[i])))
#         # Calculate the number of days between the crossing and HitRefill.
#         days_from_refill = (pd.Timestamp(row.HitRefill) - target_date).total_seconds() / (24 * 3600)
#         FIRO_space_E[project] = days_from_refill
#     return FIRO_space_E
#
# def find_FIRO_space_A(project_data, stor_elev):
#     '''
#     Calculate the target elevation for FIRO Space Component A for each project.
#
#     For each project, the function:
#     1. Retrieves the project's storage-elevation rating curve.
#     2. Converts the minimum conservation elevation to storage.
#     3. Adds the allocated FIRO storage space to determine the target storage.
#     4. Converts the target storage to elevation.
#     5. Stores the target elevation for the project.
#
#     '''
#     FIRO_space_A = {}
#     for row in project_data.itertuples():
#         project = row.Project
#         rating = stor_elev[stor_elev['Project']==project]
#         storage_min_con = np.interp(row.MinCon, rating['Elevation (ft)'], rating['Storage_KAF'])
#         target_storage = storage_min_con + row.FIROSpaceKAF
#         target_elevation = np.interp(target_storage, rating['Storage_KAF'], rating['Elevation (ft)'])
#         FIRO_space_A[project] = target_elevation
#     return FIRO_space_A
#
# def find_FIRO_space_J(project_data, rule_curves, stor_elev):
#     '''
#     Estimate the number of days from the start of drawdown until the
#     rule curve crosses the target elevation for FIRO Space Component J.
#
#     For each project, the function:
#     1. Retrieves the project's storage-elevation rating curve.
#     2. Converts the maximum convervation elevation to storage.
#     3. Subtracts the allocated FIRO storage space to determine the
#        target storage and converts it to elevation.
#     4. Restricts the rule curve to the drawdown period, from
#        DrawdownBegins to DrawdownEnds.
#     5. Identifies the first interval in which the rule curve crosses
#        the target elevation.
#     6. Linearly interpolates between adjacent rule curve values to
#        estimate the crossing date.
#     7. Calculates the elapsed time in days between the start of drawdown
#        and the estimated crossing date.
#     '''
#     FIRO_space_J = {}
#     for row in project_data.itertuples():
#         project = row.Project
#         rating = stor_elev[stor_elev['Project'] == project] # Grab rating curve
#         storage_max_con = np.interp(row.MaxCon, rating['Elevation (ft)'], rating['Storage_KAF'])
#         target_storage = storage_max_con - row.FIROSpaceKAF # space to ride above rule curve
#
#         target_elevation = np.interp(target_storage, rating['Storage_KAF'], rating['Elevation (ft)']) # find the elevation
#         rule_curve = rule_curves[project.upper()] # get in rule curve
#         drawdown_season = rule_curve.loc[row.DrawdownBegins:row.DrawdownEnds] # isolate just the drawdown season
#         # find the difference between rule curve and target elevation to know when targer elevation is crossed
#         s = drawdown_season['value'] - target_elevation
#         if target_elevation < row.MinCon:
#             print(f"Space Component J: Project {project} target elev is below min con")
#             days_from_drawdown = 0
#         else:
#             # get all value but the first, then all values but the last, multiply them compaired consecutive values
#             # greater than 0 means target elevation was crossed
#             # np.where(...)[0] returns the indexs of all points crossed, should only be one so [0] grabs that value
#             i = np.where(s.iloc[:-1].values * s.iloc[1:].values <= 0)[0][0]
#             # Interpolate to get the target date:
#             target_date = s.index[i] - pd.Timedelta(days=s.iloc[i] / (s.iloc[i+1] - s.iloc[i]))
#             # find the days from refill the firo space can ride above rule curve
#             drawdown_start = pd.Timestamp(row.DrawdownBegins)
#             days_from_drawdown = (target_date - drawdown_start).total_seconds() / (24 * 3600) # convert to days
#         FIRO_space_J[project] = days_from_drawdown
#     return FIRO_space_J
#
# def find_FIRO_space_C(project_data, rule_curves, stor_elev):
#     '''
#     Estimate the start date of FIRO Space Component C for each project.
#
#     Component C is defined by a linear guide curve that begins before
#     the refill start date and reconnects with the rule curve at the
#     specified slope-change date (RefillSlopeChange).
#
#     For each project, the function:
#     1. Skips projects without a defined slope-change date.
#     2. Calculates the target storage by adding the allocated FIRO space
#        (FIROSpaceKAF) to the minimum conservation storage (MinCon).
#     3. Converts the target storage to elevation using the project's
#        storage-elevation rating curve.
#     4. Determines the elevation where Component C reconnects with the
#        rule curve.
#     5. Calculates the linear guide curve slope between the refill start
#        date and the reconnection date.
#     6. Extrapolates backward to estimate when the guide curve reaches
#        the minimum conservation elevation.
#     7. Skips projects where the estimated start date precedes the end
#        of the drawdown period.
#     '''
#     FIRO_space_C = {}
#     for row in project_data.itertuples():
#         end_date = row.RefillSlopeChange # day that space c curve ends and reconnects with rule curve
#         if pd.isna(end_date):
#             continue # skip projects without inflection point
#         project = row.Project
#         # largest time above rule curves is when the guide curve refill begins
#         target_date = row.StartRefill # target date
#         rating = stor_elev[stor_elev['Project'] == project]
#         storage_min_con = np.interp(row.MinCon, rating['Elevation (ft)'], rating['Storage_KAF'])
#         target_storage = storage_min_con + row.FIROSpaceKAF
#         target_elevation = np.interp(target_storage, rating['Storage_KAF'], rating['Elevation (ft)'])
#         rule_curve = rule_curves[project.upper()]
#         end_elevation = rule_curve.loc[end_date].iloc[0] # this will be the elevation where space curve c ends
#         if target_elevation > end_elevation:
#             print(f'Space Component C: Project {project} is not limited by downstream control point')
#             min_con_date = row.DrawdownEnds
#         else:
#             end_date = pd.Timestamp(end_date)
#             target_date = pd.Timestamp(target_date)
#             days_between = (end_date - target_date).total_seconds() / (24 * 3600)
#             slope =  (end_elevation - target_elevation) / days_between
#
#             # Finding the days from refill start to mincon
#             days_to_min_con = (target_elevation - row.MinCon) / slope
#             min_con_date = target_date - pd.to_timedelta(days_to_min_con, unit='D')
#             # bring in day drawdown ends:
#
#             if min_con_date < pd.to_datetime(row.DrawdownEnds):
#                 print(f'Space Component C: Project {project} start of curve is before {row.DrawdownEnds}')
#                 min_con_date = row.DrawdownEnds
#         FIRO_space_C[project] = min_con_date
#     return FIRO_space_C
#
# def find_FIRO_space_I(project_data, rule_curves, stor_elev):
#     '''
#     Calculate the target elevation for FIRO Space Component I for each project.
#
#     Component I is defined by adding the allocated FIRO storage space
#     (FIROSpaceKAF) to the storage corresponding to the rule curve elevation
#     on April 1, then converting the resulting storage back to elevation.
#
#     For each project, the function:
#     1. Retrieves the project's storage-elevation rating curve and rule curve.
#     2. Identifies the rule curve elevation on April 1, 2019, and converts
#        it to storage.
#     3. Adds the allocated FIRO storage space to determine the target storage.
#     4. Converts the target storage to elevation.
#     5. Caps the target elevation at the maximum conservation elevation (MaxCon)
#        if it exceeds that limit.
#     '''
#     FIRO_space_I = {}
#     for row in project_data.itertuples():
#         project = row.Project
#         rating = stor_elev[stor_elev['Project'] == project] # Grab rating curve
#         rule_curve = rule_curves[project.upper()] # get rule curve
#         april_1_elev = rule_curve.loc["04/01/2019"].iloc[0]
#         april_1_stor = np.interp(april_1_elev, rating['Elevation (ft)'], rating['Storage_KAF'])
#         target_storage = april_1_stor + row.FIROSpaceKAF # space to ride above rule curve
#         target_elevation = np.interp(target_storage, rating['Storage_KAF'], rating['Elevation (ft)']) # find the elevation
#         if target_elevation > row.MaxCon:
#             print(f'Space Component I: No downstream space limitations for {project}')
#             target_elevation = row.MaxCon
#         FIRO_space_I[project] = target_elevation
#     return FIRO_space_I
#
# def find_FIRO_space_H(project_data, rule_curves, stor_elev): #TODO
#     '''
#     Estimate the date when the rule curve crosses the target elevation
#     for FIRO Space Component H.
#
#     Component H is defined relative to the spillway crest. The allocated
#     FIRO storage space (FIROSpaceKAF) is subtracted from the storage at
#     the spillway crest to determine the target storage, which is then
#     converted to elevation. The rule curve is searched between the end
#     of drawdown and the refill date to identify when it crosses this
#     target elevation.
#
#     For each project, the function:
#     1. Skips projects without a defined spillway crest elevation.
#     2. Converts the spillway crest elevation to storage using the
#        project's storage-elevation rating curve.
#     3. Subtracts the allocated FIRO storage space to determine the
#        target storage and converts it to elevation.
#     4. Skips projects where the target elevation is below the minimum
#        conservation elevation (MinCon), indicating that downstream storage
#        is not a limiting factor.
#     5. Searches the rule curve between DrawdownEnds and HitRefill
#        for a crossing of the target elevation.
#     6. Linearly interpolates between adjacent rule curve values to
#        estimate the crossing date.
#     '''
#     FIRO_space_H = {}
#     for row in project_data.itertuples():
#         spillway_crest = row.SpillwayCrest
#         if pd.isna(spillway_crest):
#             continue
#         project = row.Project
#         rating = stor_elev[stor_elev['Project'] == project] # Grab rating curve
#         storage_spillway_crest = np.interp(spillway_crest, rating['Elevation (ft)'], rating['Storage_KAF'])
#
#         target_storage = storage_spillway_crest - row.FIROSpaceKAF # space to ride above rule curve
#         target_elevation = np.interp(target_storage, rating['Storage_KAF'], rating['Elevation (ft)']) # find the elevation
#         if target_elevation < row.MinCon:
#             print(f"Space Component H: Target elevation is less than Min Con for {project}.")
#             target_date = row.StartRefill
#         else:
#             rule_curve = rule_curves[project.upper()] # get rule curve
#             # isolate just flood and refill part of rule curve
#             refill_season = rule_curve.loc[row.StartRefill:row.HitRefill]
#             # find the difference between rule curve and target elevation to know when targer elevation is crossed
#             s = refill_season['value'] - target_elevation
#             # get all value but the first, then all values but the last, multiply them compaired consecutive values
#             # greater than 0 means target elevation was crossed
#             # np.where(...)[0] returns the indexs of all points crossed, should only be one so [0] grabs that value
#             i = np.where(s.iloc[:-1].values * s.iloc[1:].values <= 0)[0][0]
#             # Interpolate to get the target date:
#             target_date = s.index[i] - pd.Timedelta(days=s.iloc[i] / (s.iloc[i+1] - s.iloc[i]))
#             # find the days from refill the firo space can ride above rule curve
#
#         FIRO_space_H[project] = target_date
#     return FIRO_space_H
#
# def find_all_FIRO_spaces(alternative_dict, rule_curves, stor_elev):
#     data_dict = {}
#     for alternative, project_data in alternative_dict.items():
#         print(f"Computing alternative: {alternative}")
#         # Run each FIRO space calculation
#         firo_space_A = find_FIRO_space_A(project_data, stor_elev)
#         firo_space_H = find_FIRO_space_H(project_data, rule_curves, stor_elev)
#         firo_space_E = find_FIRO_space_E(project_data, rule_curves, stor_elev)
#         firo_space_I = find_FIRO_space_I(project_data, rule_curves, stor_elev)
#         firo_space_C = find_FIRO_space_C(project_data, rule_curves, stor_elev)
#         firo_space_J = find_FIRO_space_J(project_data, rule_curves, stor_elev)
#
#         # Add each rule's results as a row, with projects as columns
#         firo_spaces = {"FIROSpaceKAF": project_data.set_index("Project")["FIROSpaceKAF"].to_dict(),
#             "LimitingFactor": project_data.set_index("Project")["LimitingFactor"].to_dict(),
#             "A": firo_space_A, "C": firo_space_C, "E": firo_space_E,  "H": firo_space_H,
#             "I": firo_space_I, "J": firo_space_J, "K": firo_space_E}  # K uses the same values as E
#         df = pd.DataFrame(firo_spaces)
#         df = df.T
#         df.index.name = "FIROSpace"
#         data_dict[alternative] = df
#     return data_dict
#
#
# #### code here
# if __name__ == "main" or __name__ == "__main__":
#     # bring in rule curves:
#     if REUPLOAD_RULE_CURVE:
#         rule_curves = load_data_dict(RULE_CURVES)
#         with open(RULE_CURVES_PICKLE, "wb") as file:
#             pickle.dump(rule_curves, file)
#     else:
#         with open(RULE_CURVES_PICKLE, 'rb') as file:
#             rule_curves = pickle.load(file)
#             clean_rule_curves(rule_curves)    # limit rule curve to one year and create a storage column
#     # bring in rating curves:
#     stor_elev = pd.read_excel(STOR_ELEV)
#     stor_elev['Storage_KAF'] = stor_elev["Storage (ac-ft)"] / 1000 # add a col with storage in kaf
#     # bring in project data and calculate some columns for the df
#     project_data = pd.read_csv(PROJECT_DATA)
#     # bring in control point space
#     control_point_space = pd.read_csv(CONTROL_POINT_SPACE).set_index("Location")
#
#
#  ###################### not done
#  # "find_FIRO_space_X" funtions were made to use the project_data df that has a columns called "FIROSpaceKAF"
#  # which defines it's firo space
# ############################# EACH OF THE
#
#     # find FRIO Spaces:
#     data_dict = find_all_FIRO_spaces(alternative_dict, rule_curves, stor_elev)
#
#
#
#
#
#
#
#
#
#
# END COMMENTED FIRO WORK: earlier component geometry

if __name__ == "__main__":
    print("Component geometry runs in FIRO_COMPONENTS. Earlier work is retained here as comments.")
