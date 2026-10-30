# Clinic Compass Setup Guide

This guide sets up the interactive clinic search from a fresh clone. Use the
`feature/interactive-clinic-search` branch; it includes the road-routing feature.

## 1. Install prerequisites

Install Git and Python 3.10 or later. Check that Python is available:

```bash
python3 --version
git --version
```

## 2. Clone the project

In Terminal (macOS/Linux) or a terminal with Git installed, run:

```bash
git clone --branch feature/interactive-clinic-search --single-branch https://github.com/tingclarice/clinic-compass.git
cd clinic-compass
```

If you already cloned the repository, open a terminal in its folder and run:

```bash
git switch feature/interactive-clinic-search
git pull
```

## 3. Create a virtual environment and install dependencies

From the project root (`clinic-compass`), run:

**macOS/Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

**Windows PowerShell**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The dependencies include JupyterLab and the notebook widget support needed to
render the interactive map.

## 4. Start the interactive search

Keep the terminal in the project root, activate `.venv` if it is not already
active, then run:

```bash
python -m jupyter lab notebooks/02_clinic_search.ipynb
```

JupyterLab will print a local URL. Open it in your browser, select the Python
kernel from this project's `.venv` if prompted, then run the notebook cell
(**Run** or **Run All**).

On the first run, the project downloads the drivable OpenStreetMap road network
for the study area. Internet access is required. The graph is cached under
`.cache/` for subsequent runs. The clinic and boundary datasets are already
included in the repository; run `notebooks/01_data_collection.ipynb` only if
those processed files are missing or you intend to refresh the source data.

## 5. Use the map

1. Click the map to set the user's starting location.
2. Choose a medical service, date, time, and search radius.
3. Click **Cari klinik**.
4. Use the directional buttons to adjust the location by 50 metres, then search
   again if needed.

Results are filtered to clinics whose recorded schedule says they are open at
the selected time, and ranked by road distance. If no suitable reachable clinic
is found, the radius expands to 5 km. Clinics with missing or unparseable hours
are treated as **unknown**, never as open. Until verified operating-hours data
is added, the app may return few or no results.

## Troubleshooting

- **`No module named 'src'`:** launch JupyterLab using the command above while
  your terminal is in the repository root. Do not launch the notebook from a
  detached preview or from a different folder.
- **`No module named ...` for a dependency:** activate this project's `.venv`
  and run `python -m pip install -r requirements.txt` again. Confirm the
  notebook is using the `.venv` Python kernel.
- **Map output shows `HBox(children=(Map(...` instead of a map:** use JupyterLab
  launched by the command above, rather than a notebook preview that does not
  render ipyleaflet widgets.
- **No results:** inspect the result summary. Missing clinic hours are excluded
  because they cannot be verified as open.
- **Stop JupyterLab:** focus the terminal where it is running and press
  `Ctrl+C`.
