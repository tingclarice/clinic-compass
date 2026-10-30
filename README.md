# clinic-compass
AFL 2 Computer Graphics: GIS Project

Clinic Compass is a GIS-based interactive application that helps users find the most suitable clinics in West Surabaya based on location, medical services, operating hours, and shortest road distance.

Built with Python and geospatial analysis libraries, MediRoute uses Buffer and Spatial Join operations to identify nearby clinics, filters results based on user requirements, and applies Dijkstra’s algorithm to calculate the shortest routes through the road network. The application also supports automatic search radius expansion when no suitable clinics are found within the initial radius.

Developed as a Geographic Information Systems (GIS) project using OpenStreetMap data, GeoPandas, Shapely, Pandas, OSMnx, NetworkX, and Matplotlib.

Project scope: Asemrowo, Benowo, Lakarsantri, Pakal, Sambikerep, Sukomanunggal, and Tandes, Surabaya, Indonesia.

The road-routing module downloads the OSM drivable road graph for the study area on
first use and caches it locally under `.cache/`. Routing uses projected distances
and Dijkstra's shortest-path algorithm; the cache can be removed to fetch an
updated road network.

Run `notebooks/02_clinic_search.ipynb` for the interactive map. Click to set a
starting point, select a service and search time, then search within a 1, 3, or
5 km radius. If no verified-open, reachable clinic matches, the search expands
to 5 km. Clinics with unknown operating hours are excluded and reported separately.
