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