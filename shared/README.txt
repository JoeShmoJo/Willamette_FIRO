SHARED DATA TRANSITION

Formerly the repository-root data/ folder. Contents were relocated intact.
The common_data subfolder and legacy root datasets are intentionally preserved
until their sources and differences have been reviewed. No authoritative
source selection or dataset consolidation is implied by this move.
Project-specific derived FIRO inputs remain in FIRO_COMPONENTS/data/.

Original notes follow:

This folder houses script inputs. Individual files should not exceed 50 mb. Watch git commit warnings about size.

common_data: houses data that is used by a bunch of different scripts (e.g. elev-stor tables, etc)

datasets_sharepoint: The true authoritative datasets live on the CW3E SharePoint site.
The files here are just copies of that that we can use in scripts.
Ignored by git.

temp_data: Completely temporary data that might be produced as an interim product by scripts to save time. All files here can be deleted with no problems.
Ignored by git.


LP3Residual.csv: Residual flood frequency curves from a given date through the end of flood season
	sourced from: ResidualVolumeFrequency\out
	On 9/1/2026
Shared Python utility modules now live in shared/modules/.
