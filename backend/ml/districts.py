"""
Single source of truth for the 107 Pakistani districts used throughout this
project (synthetic dataset generation, API metadata, flood watch, etc.).

SYNTHETIC DATA NOTICE: the climate parameters below are hand-tuned, plausible
values based on general knowledge of Pakistan's geography and climate zones.
They are NOT measured meteorological records. They exist purely to make the
generated dataset behave in a realistic, internally-consistent way (e.g.
Sibi runs hotter than Gilgit, Karachi is more humid than Quetta) for a
research/teaching MLOps demo — never treat them as verified climate data.

Per-district parameters:
- province: administrative grouping. The three ICT/AJK/GB districts are
  grouped under the single label "Capital/AJK/GB" for simplicity, matching
  how this project's district list was scoped (they are technically three
  distinct federal units: Islamabad Capital Territory, Azad Jammu &
  Kashmir, and Gilgit-Baltistan).
- lat, lon: approximate coordinates of the district's main city (degrees).
- temp_offset_c: added to the national seasonal temperature curve in
  generate_data.py. Positive for hot, low-lying southern/desert districts
  (e.g. Sibi, Rahim Yar Khan, Dera Ghazi Khan, Sukkur); negative for cool,
  high-altitude northern/hilly districts (Swat, Abbottabad, Gilgit,
  Muzaffarabad, Quetta, Skardu, Chitral).
- monsoon_strength: 0-1 scaling factor for the Jul-Sep monsoon rainfall/
  humidity boost. High along the eastern monsoon corridor (Sialkot, Lahore,
  Islamabad, Peshawar); near zero in the arid west/coast/high mountains
  (Gwadar, Kech, Quetta, Chagai, Skardu), which lie outside the main
  monsoon corridor or in its rain shadow.
- humidity_offset: added to the national humidity curve. Positive for
  coastal districts moderated by the Arabian Sea (Karachi, Gwadar, Badin,
  Thatta); negative for dry interior desert districts and dry mountain air
  (e.g. Bahawalpur, Quetta, Gilgit, Tharparkar, Chagai).
- canal_flow_baseline_cusecs: typical baseline canal discharge. High
  (400-600) for canal-command districts fed by the Indus Basin Irrigation
  System — most of Punjab and Sindh, plus Nasirabad/Jaffarabad in
  Balochistan; low (30-150) for barani (rain-fed), desert, or
  tubewell-dependent districts (Rawalpindi, Abbottabad, Swat, Quetta,
  Gwadar, Gilgit, Muzaffarabad, Tharparkar, Chagai, most of KPK's hills).
- river_exposure (Phase 5.5): 0.0-1.0 rating of how exposed a district is to
  Indus/Kabul/Chenab/Jhelum riverine and flash flooding — used as the
  "exposure" component of the Flood Risk Index (see docs/FLOOD_RISK.md).
  HIGH (0.7-1.0): districts directly on the Indus/Kabul mainstem or in the
  Indus delta, historically hit hardest by riverine flooding (e.g. the 2010
  and 2022 floods) — Dera Ismail Khan, Tank, Nowshera, Charsadda, the
  Peshawar valley, Rajanpur, Layyah, Muzaffargarh, Dera Ghazi Khan, Rahim
  Yar Khan, Jacobabad, Kashmore, Shikarpur, Ghotki, Sukkur, Larkana, Dadu,
  Jamshoro, Hyderabad, Matiari, Thatta, Sujawal, Badin, Jaffarabad, and
  similar Indus-mainstem districts. MODERATE (0.4-0.6): the Chenab/Ravi/
  Jhelum tributary belt (Multan, Jhang, Chiniot, Sialkot, Gujranwala,
  Gujrat, Bahawalpur, etc.) — real but lower flood risk than the Indus
  mainstem. LOW (0.0-0.3): barani/highland/desert districts far from major
  rivers (Quetta, Chakwal, Gilgit, Skardu, Chitral, Tharparkar, etc.). Each
  district's inline comment states the specific justification.
"""

DISTRICTS = {
    # --- Punjab (34) ---------------------------------------------------
    "Lahore": {"province": "Punjab", "lat": 31.5497, "lon": 74.3436, "temp_offset_c": 0.5, "monsoon_strength": 0.75, "humidity_offset": 2, "canal_flow_baseline_cusecs": 450, "river_exposure": 0.45},  # on the Ravi — moderate riverine exposure
    "Faisalabad": {"province": "Punjab", "lat": 31.4504, "lon": 73.1350, "temp_offset_c": 1.0, "monsoon_strength": 0.60, "humidity_offset": 0, "canal_flow_baseline_cusecs": 480, "river_exposure": 0.3},  # interior canal colony, off the main rivers
    "Rawalpindi": {"province": "Punjab", "lat": 33.6007, "lon": 73.0679, "temp_offset_c": -2.0, "monsoon_strength": 0.65, "humidity_offset": 3, "canal_flow_baseline_cusecs": 90, "river_exposure": 0.2},  # barani (rain-fed), not canal-command; Soan is a minor stream
    "Gujranwala": {"province": "Punjab", "lat": 32.1877, "lon": 74.1945, "temp_offset_c": 0.3, "monsoon_strength": 0.70, "humidity_offset": 1, "canal_flow_baseline_cusecs": 460, "river_exposure": 0.45},  # near the Chenab — moderate exposure
    "Multan": {"province": "Punjab", "lat": 30.1575, "lon": 71.5249, "temp_offset_c": 3.5, "monsoon_strength": 0.40, "humidity_offset": -3, "canal_flow_baseline_cusecs": 550, "river_exposure": 0.55},  # on the Chenab — moderate-high exposure
    "Sargodha": {"province": "Punjab", "lat": 32.0836, "lon": 72.6711, "temp_offset_c": 0.8, "monsoon_strength": 0.55, "humidity_offset": 0, "canal_flow_baseline_cusecs": 470, "river_exposure": 0.4},  # Chenab/Jhelum doab — moderate exposure
    "Sialkot": {"province": "Punjab", "lat": 32.4945, "lon": 74.5229, "temp_offset_c": 0.0, "monsoon_strength": 0.80, "humidity_offset": 3, "canal_flow_baseline_cusecs": 420, "river_exposure": 0.45},  # strongest monsoon exposure in Punjab; Chenab-adjacent
    "Bahawalpur": {"province": "Punjab", "lat": 29.3956, "lon": 71.6836, "temp_offset_c": 3.0, "monsoon_strength": 0.25, "humidity_offset": -5, "canal_flow_baseline_cusecs": 500, "river_exposure": 0.4},  # Sutlej belt — moderate exposure
    "Bahawalnagar": {"province": "Punjab", "lat": 29.9989, "lon": 73.2578, "temp_offset_c": 2.8, "monsoon_strength": 0.30, "humidity_offset": -4, "canal_flow_baseline_cusecs": 480, "river_exposure": 0.4},  # Sutlej belt — moderate exposure
    "Rahim Yar Khan": {"province": "Punjab", "lat": 28.4212, "lon": 70.2989, "temp_offset_c": 4.0, "monsoon_strength": 0.20, "humidity_offset": -5, "canal_flow_baseline_cusecs": 520, "river_exposure": 0.75},  # hot southern Punjab, Indus/Panjnad confluence — HIGH
    "Dera Ghazi Khan": {"province": "Punjab", "lat": 30.0561, "lon": 70.6339, "temp_offset_c": 4.2, "monsoon_strength": 0.25, "humidity_offset": -5, "canal_flow_baseline_cusecs": 400, "river_exposure": 0.8},  # hot southern Punjab, directly on the Indus — HIGH
    "Muzaffargarh": {"province": "Punjab", "lat": 30.0703, "lon": 71.1933, "temp_offset_c": 3.8, "monsoon_strength": 0.25, "humidity_offset": -4, "canal_flow_baseline_cusecs": 510, "river_exposure": 0.8},  # between the Chenab and Indus — HIGH
    "Jhang": {"province": "Punjab", "lat": 31.2781, "lon": 72.3317, "temp_offset_c": 2.0, "monsoon_strength": 0.40, "humidity_offset": -2, "canal_flow_baseline_cusecs": 490, "river_exposure": 0.5},  # Chenab/Jhelum confluence — moderate exposure
    "Sahiwal": {"province": "Punjab", "lat": 30.6682, "lon": 73.1114, "temp_offset_c": 1.0, "monsoon_strength": 0.55, "humidity_offset": 0, "canal_flow_baseline_cusecs": 470, "river_exposure": 0.35},  # Ravi belt — moderate exposure
    "Okara": {"province": "Punjab", "lat": 30.8081, "lon": 73.4534, "temp_offset_c": 0.8, "monsoon_strength": 0.55, "humidity_offset": 0, "canal_flow_baseline_cusecs": 460, "river_exposure": 0.35},  # Ravi belt — moderate exposure
    "Kasur": {"province": "Punjab", "lat": 31.1187, "lon": 74.4467, "temp_offset_c": 0.5, "monsoon_strength": 0.70, "humidity_offset": 2, "canal_flow_baseline_cusecs": 440, "river_exposure": 0.35},  # Sutlej border belt — moderate exposure
    "Vehari": {"province": "Punjab", "lat": 30.0453, "lon": 72.3489, "temp_offset_c": 1.5, "monsoon_strength": 0.45, "humidity_offset": -2, "canal_flow_baseline_cusecs": 480, "river_exposure": 0.35},  # Sutlej belt — moderate exposure
    "Sheikhupura": {"province": "Punjab", "lat": 31.7130, "lon": 73.9779, "temp_offset_c": 0.3, "monsoon_strength": 0.70, "humidity_offset": 2, "canal_flow_baseline_cusecs": 450, "river_exposure": 0.35},  # Ravi/Chenab doab — moderate exposure
    "Attock": {"province": "Punjab", "lat": 33.7667, "lon": 72.3597, "temp_offset_c": -1.0, "monsoon_strength": 0.65, "humidity_offset": 1, "canal_flow_baseline_cusecs": 110, "river_exposure": 0.75},  # sits at the Indus-Kabul confluence — HIGH, despite otherwise barani terrain
    "Mianwali": {"province": "Punjab", "lat": 32.5850, "lon": 71.5440, "temp_offset_c": 2.0, "monsoon_strength": 0.35, "humidity_offset": -3, "canal_flow_baseline_cusecs": 300, "river_exposure": 0.75},  # directly on the Indus — HIGH
    "Bhakkar": {"province": "Punjab", "lat": 31.6250, "lon": 71.0650, "temp_offset_c": 2.5, "monsoon_strength": 0.30, "humidity_offset": -4, "canal_flow_baseline_cusecs": 280, "river_exposure": 0.7},  # Thal desert district bordering the Indus — HIGH
    "Layyah": {"province": "Punjab", "lat": 30.9693, "lon": 70.9428, "temp_offset_c": 3.0, "monsoon_strength": 0.30, "humidity_offset": -3, "canal_flow_baseline_cusecs": 460, "river_exposure": 0.8},  # Indus/Chenab doab — HIGH
    "Rajanpur": {"province": "Punjab", "lat": 29.1044, "lon": 70.3286, "temp_offset_c": 4.5, "monsoon_strength": 0.22, "humidity_offset": -5, "canal_flow_baseline_cusecs": 420, "river_exposure": 0.85},  # low-lying Indus floodplain, Sulaiman hilltorrent outfall — HIGH
    "Khanewal": {"province": "Punjab", "lat": 30.3015, "lon": 71.9319, "temp_offset_c": 1.8, "monsoon_strength": 0.45, "humidity_offset": -1, "canal_flow_baseline_cusecs": 500, "river_exposure": 0.35},  # interior doab, off the main rivers — moderate
    "Lodhran": {"province": "Punjab", "lat": 29.5406, "lon": 71.6320, "temp_offset_c": 2.5, "monsoon_strength": 0.35, "humidity_offset": -2, "canal_flow_baseline_cusecs": 470, "river_exposure": 0.4},  # near the Sutlej/Chenab confluence — moderate
    "Toba Tek Singh": {"province": "Punjab", "lat": 30.9709, "lon": 72.4831, "temp_offset_c": 1.2, "monsoon_strength": 0.55, "humidity_offset": 0, "canal_flow_baseline_cusecs": 480, "river_exposure": 0.3},  # interior canal colony — moderate-low
    "Chiniot": {"province": "Punjab", "lat": 31.7200, "lon": 72.9780, "temp_offset_c": 1.5, "monsoon_strength": 0.55, "humidity_offset": 0, "canal_flow_baseline_cusecs": 470, "river_exposure": 0.5},  # directly on the Chenab — moderate
    "Hafizabad": {"province": "Punjab", "lat": 32.0710, "lon": 73.6880, "temp_offset_c": 0.5, "monsoon_strength": 0.65, "humidity_offset": 1, "canal_flow_baseline_cusecs": 460, "river_exposure": 0.4},  # Chenab belt — moderate
    "Mandi Bahauddin": {"province": "Punjab", "lat": 32.5850, "lon": 73.4930, "temp_offset_c": 0.3, "monsoon_strength": 0.65, "humidity_offset": 1, "canal_flow_baseline_cusecs": 460, "river_exposure": 0.45},  # between the Chenab and Jhelum — moderate
    "Gujrat": {"province": "Punjab", "lat": 32.5740, "lon": 74.0790, "temp_offset_c": 0.2, "monsoon_strength": 0.70, "humidity_offset": 2, "canal_flow_baseline_cusecs": 450, "river_exposure": 0.5},  # Chenab/Jhelum doab — moderate
    "Jhelum": {"province": "Punjab", "lat": 32.9425, "lon": 73.7257, "temp_offset_c": -0.5, "monsoon_strength": 0.65, "humidity_offset": 2, "canal_flow_baseline_cusecs": 200, "river_exposure": 0.55},  # directly on the Jhelum river — moderate-high
    "Chakwal": {"province": "Punjab", "lat": 32.9328, "lon": 72.8630, "temp_offset_c": -1.5, "monsoon_strength": 0.55, "humidity_offset": 1, "canal_flow_baseline_cusecs": 70, "river_exposure": 0.15},  # barani/highland — LOW, no major river
    "Pakpattan": {"province": "Punjab", "lat": 30.3411, "lon": 73.3928, "temp_offset_c": 2.2, "monsoon_strength": 0.40, "humidity_offset": -2, "canal_flow_baseline_cusecs": 470, "river_exposure": 0.4},  # on the Sutlej — moderate
    "Nankana Sahib": {"province": "Punjab", "lat": 31.4500, "lon": 73.7000, "temp_offset_c": 0.6, "monsoon_strength": 0.65, "humidity_offset": 1, "canal_flow_baseline_cusecs": 450, "river_exposure": 0.35},  # Ravi belt — moderate

    # --- Sindh (24) ------------------------------------------------------
    "Karachi": {"province": "Sindh", "lat": 24.8607, "lon": 67.0011, "temp_offset_c": 1.0, "monsoon_strength": 0.15, "humidity_offset": 15, "canal_flow_baseline_cusecs": 200, "river_exposure": 0.25},  # coastal, urban — moderated temp, low canal command, not on the Indus mainstem
    "Hyderabad": {"province": "Sindh", "lat": 25.3960, "lon": 68.3578, "temp_offset_c": 2.5, "monsoon_strength": 0.20, "humidity_offset": 6, "canal_flow_baseline_cusecs": 480, "river_exposure": 0.8},  # directly on the Indus, downstream of Kotri Barrage — HIGH
    "Sukkur": {"province": "Sindh", "lat": 27.7052, "lon": 68.8574, "temp_offset_c": 4.5, "monsoon_strength": 0.15, "humidity_offset": -2, "canal_flow_baseline_cusecs": 560, "river_exposure": 0.9},  # Sukkur Barrage on the Indus, hot upper Sindh — HIGH
    "Larkana": {"province": "Sindh", "lat": 27.5590, "lon": 68.2120, "temp_offset_c": 4.3, "monsoon_strength": 0.15, "humidity_offset": -2, "canal_flow_baseline_cusecs": 520, "river_exposure": 0.8},  # Indus floodplain, hit hard in 2010/2022 floods — HIGH
    "Shaheed Benazirabad": {"province": "Sindh", "lat": 26.2442, "lon": 68.4100, "temp_offset_c": 3.8, "monsoon_strength": 0.15, "humidity_offset": -1, "canal_flow_baseline_cusecs": 500, "river_exposure": 0.75},  # Indus belt — HIGH
    "Mirpurkhas": {"province": "Sindh", "lat": 25.5271, "lon": 69.0113, "temp_offset_c": 3.0, "monsoon_strength": 0.20, "humidity_offset": 4, "canal_flow_baseline_cusecs": 460, "river_exposure": 0.35},  # interior Sindh, off the Indus mainstem — moderate
    "Khairpur": {"province": "Sindh", "lat": 27.5296, "lon": 68.7594, "temp_offset_c": 4.2, "monsoon_strength": 0.15, "humidity_offset": -2, "canal_flow_baseline_cusecs": 540, "river_exposure": 0.8},  # directly on the Indus — HIGH
    "Dadu": {"province": "Sindh", "lat": 26.7310, "lon": 67.7750, "temp_offset_c": 4.0, "monsoon_strength": 0.15, "humidity_offset": -1, "canal_flow_baseline_cusecs": 470, "river_exposure": 0.8},  # Indus/Manchar Lake floodplain — HIGH
    "Badin": {"province": "Sindh", "lat": 24.6560, "lon": 68.8380, "temp_offset_c": 2.0, "monsoon_strength": 0.20, "humidity_offset": 12, "canal_flow_baseline_cusecs": 430, "river_exposure": 0.75},  # coastal / Indus delta — HIGH
    "Thatta": {"province": "Sindh", "lat": 24.7461, "lon": 67.9243, "temp_offset_c": 1.8, "monsoon_strength": 0.20, "humidity_offset": 12, "canal_flow_baseline_cusecs": 420, "river_exposure": 0.85},  # coastal / Indus delta — HIGH
    "Jacobabad": {"province": "Sindh", "lat": 28.2822, "lon": 68.4356, "temp_offset_c": 6.0, "monsoon_strength": 0.12, "humidity_offset": -5, "canal_flow_baseline_cusecs": 480, "river_exposure": 0.8},  # among the hottest places on Earth, Indus floodplain — HIGH
    "Kashmore": {"province": "Sindh", "lat": 28.4319, "lon": 69.5828, "temp_offset_c": 5.0, "monsoon_strength": 0.15, "humidity_offset": -3, "canal_flow_baseline_cusecs": 500, "river_exposure": 0.85},  # Guddu Barrage on the Indus — HIGH
    "Shikarpur": {"province": "Sindh", "lat": 27.9564, "lon": 68.6383, "temp_offset_c": 4.8, "monsoon_strength": 0.15, "humidity_offset": -2, "canal_flow_baseline_cusecs": 490, "river_exposure": 0.8},  # Indus floodplain — HIGH
    "Ghotki": {"province": "Sindh", "lat": 28.0064, "lon": 69.3153, "temp_offset_c": 4.6, "monsoon_strength": 0.15, "humidity_offset": -2, "canal_flow_baseline_cusecs": 510, "river_exposure": 0.8},  # Guddu Barrage command area — HIGH
    "Sanghar": {"province": "Sindh", "lat": 26.0464, "lon": 68.9481, "temp_offset_c": 3.5, "monsoon_strength": 0.18, "humidity_offset": -1, "canal_flow_baseline_cusecs": 440, "river_exposure": 0.35},  # interior Sindh, off the Indus mainstem — moderate
    "Jamshoro": {"province": "Sindh", "lat": 25.4300, "lon": 68.2800, "temp_offset_c": 3.8, "monsoon_strength": 0.18, "humidity_offset": 2, "canal_flow_baseline_cusecs": 460, "river_exposure": 0.8},  # Kotri Barrage on the Indus — HIGH
    "Naushahro Feroze": {"province": "Sindh", "lat": 26.8400, "lon": 68.1250, "temp_offset_c": 4.0, "monsoon_strength": 0.15, "humidity_offset": -2, "canal_flow_baseline_cusecs": 480, "river_exposure": 0.75},  # Indus belt — HIGH
    "Matiari": {"province": "Sindh", "lat": 25.5950, "lon": 68.4450, "temp_offset_c": 2.8, "monsoon_strength": 0.20, "humidity_offset": 4, "canal_flow_baseline_cusecs": 460, "river_exposure": 0.8},  # directly on the Indus, near Hyderabad — HIGH
    "Tando Allahyar": {"province": "Sindh", "lat": 25.4600, "lon": 68.7150, "temp_offset_c": 2.9, "monsoon_strength": 0.20, "humidity_offset": 4, "canal_flow_baseline_cusecs": 450, "river_exposure": 0.65},  # lower Indus belt — moderate-high
    "Tando Muhammad Khan": {"province": "Sindh", "lat": 25.1233, "lon": 68.5350, "temp_offset_c": 2.3, "monsoon_strength": 0.20, "humidity_offset": 8, "canal_flow_baseline_cusecs": 430, "river_exposure": 0.7},  # near the Indus delta — HIGH
    "Qambar Shahdadkot": {"province": "Sindh", "lat": 27.8267, "lon": 67.9083, "temp_offset_c": 4.2, "monsoon_strength": 0.15, "humidity_offset": -2, "canal_flow_baseline_cusecs": 480, "river_exposure": 0.75},  # Indus/Manchar floodplain — HIGH
    "Sujawal": {"province": "Sindh", "lat": 24.6000, "lon": 68.0667, "temp_offset_c": 1.7, "monsoon_strength": 0.20, "humidity_offset": 13, "canal_flow_baseline_cusecs": 400, "river_exposure": 0.85},  # coastal Indus delta — HIGH
    "Tharparkar": {"province": "Sindh", "lat": 24.8800, "lon": 70.2650, "temp_offset_c": 3.5, "monsoon_strength": 0.10, "humidity_offset": -8, "canal_flow_baseline_cusecs": 30, "river_exposure": 0.1},  # Thar desert, far from any river — LOW
    "Umerkot": {"province": "Sindh", "lat": 25.3617, "lon": 69.7361, "temp_offset_c": 3.3, "monsoon_strength": 0.12, "humidity_offset": -6, "canal_flow_baseline_cusecs": 60, "river_exposure": 0.15},  # desert edge, far from the Indus — LOW

    # --- Khyber Pakhtunkhwa (31) -------------------------------------------
    "Peshawar": {"province": "Khyber Pakhtunkhwa", "lat": 34.0151, "lon": 71.5249, "temp_offset_c": -0.5, "monsoon_strength": 0.75, "humidity_offset": 2, "canal_flow_baseline_cusecs": 380, "river_exposure": 0.7},  # Kabul river valley — HIGH
    "Mardan": {"province": "Khyber Pakhtunkhwa", "lat": 34.1989, "lon": 72.0404, "temp_offset_c": -0.3, "monsoon_strength": 0.70, "humidity_offset": 1, "canal_flow_baseline_cusecs": 400, "river_exposure": 0.55},  # Kabul river belt — moderate-high
    "Swat": {"province": "Khyber Pakhtunkhwa", "lat": 34.7717, "lon": 72.3604, "temp_offset_c": -5.0, "monsoon_strength": 0.60, "humidity_offset": 3, "canal_flow_baseline_cusecs": 120, "river_exposure": 0.5},  # hilly, barani, but the Swat river has a history of destructive flash floods — moderate
    "Abbottabad": {"province": "Khyber Pakhtunkhwa", "lat": 34.1463, "lon": 73.2117, "temp_offset_c": -4.5, "monsoon_strength": 0.65, "humidity_offset": 3, "canal_flow_baseline_cusecs": 100, "river_exposure": 0.2},  # hilly, barani — LOW
    "Dera Ismail Khan": {"province": "Khyber Pakhtunkhwa", "lat": 31.8313, "lon": 70.9018, "temp_offset_c": 2.5, "monsoon_strength": 0.35, "humidity_offset": -3, "canal_flow_baseline_cusecs": 250, "river_exposure": 0.85},  # hot southern KPK, directly on the Indus — HIGH
    "Charsadda": {"province": "Khyber Pakhtunkhwa", "lat": 34.1497, "lon": 71.7405, "temp_offset_c": -0.5, "monsoon_strength": 0.72, "humidity_offset": 1, "canal_flow_baseline_cusecs": 410, "river_exposure": 0.85},  # Kabul/Swat river confluence, devastated in the 2010 floods — HIGH
    "Nowshera": {"province": "Khyber Pakhtunkhwa", "lat": 34.0154, "lon": 71.9747, "temp_offset_c": -0.2, "monsoon_strength": 0.70, "humidity_offset": 1, "canal_flow_baseline_cusecs": 390, "river_exposure": 0.85},  # on the Kabul river, devastated in the 2010 floods — HIGH
    "Bannu": {"province": "Khyber Pakhtunkhwa", "lat": 32.9853, "lon": 70.6027, "temp_offset_c": 2.0, "monsoon_strength": 0.30, "humidity_offset": -3, "canal_flow_baseline_cusecs": 260, "river_exposure": 0.45},  # Kurram/Tochi river belt — moderate
    "Swabi": {"province": "Khyber Pakhtunkhwa", "lat": 34.1200, "lon": 72.4700, "temp_offset_c": -0.2, "monsoon_strength": 0.70, "humidity_offset": 1, "canal_flow_baseline_cusecs": 380, "river_exposure": 0.6},  # between the Indus and Kabul rivers — moderate-high
    "Kohat": {"province": "Khyber Pakhtunkhwa", "lat": 33.5850, "lon": 71.4420, "temp_offset_c": 0.5, "monsoon_strength": 0.45, "humidity_offset": -2, "canal_flow_baseline_cusecs": 150, "river_exposure": 0.25},  # hilly, semi-arid — low-moderate
    "Karak": {"province": "Khyber Pakhtunkhwa", "lat": 33.1170, "lon": 71.0950, "temp_offset_c": 1.0, "monsoon_strength": 0.35, "humidity_offset": -4, "canal_flow_baseline_cusecs": 100, "river_exposure": 0.2},  # hilly, dry — LOW
    "Hangu": {"province": "Khyber Pakhtunkhwa", "lat": 33.5310, "lon": 71.0570, "temp_offset_c": -0.5, "monsoon_strength": 0.40, "humidity_offset": -2, "canal_flow_baseline_cusecs": 90, "river_exposure": 0.2},  # hilly — LOW
    "Lakki Marwat": {"province": "Khyber Pakhtunkhwa", "lat": 32.6070, "lon": 70.9110, "temp_offset_c": 2.2, "monsoon_strength": 0.30, "humidity_offset": -4, "canal_flow_baseline_cusecs": 180, "river_exposure": 0.4},  # Kurram/Gambila hill-torrent belt — moderate
    "Tank": {"province": "Khyber Pakhtunkhwa", "lat": 32.2170, "lon": 70.3830, "temp_offset_c": 2.8, "monsoon_strength": 0.30, "humidity_offset": -4, "canal_flow_baseline_cusecs": 200, "river_exposure": 0.75},  # adjacent to the Indus floodplain near D.I. Khan — HIGH
    "Dir Lower": {"province": "Khyber Pakhtunkhwa", "lat": 34.7460, "lon": 71.8760, "temp_offset_c": -3.0, "monsoon_strength": 0.60, "humidity_offset": 3, "canal_flow_baseline_cusecs": 100, "river_exposure": 0.4},  # Panjkora river valley — moderate
    "Dir Upper": {"province": "Khyber Pakhtunkhwa", "lat": 35.2080, "lon": 71.8760, "temp_offset_c": -6.0, "monsoon_strength": 0.50, "humidity_offset": 2, "canal_flow_baseline_cusecs": 60, "river_exposure": 0.3},  # mountainous headwaters — low-moderate
    "Chitral": {"province": "Khyber Pakhtunkhwa", "lat": 35.8511, "lon": 71.7864, "temp_offset_c": -7.0, "monsoon_strength": 0.15, "humidity_offset": -6, "canal_flow_baseline_cusecs": 50, "river_exposure": 0.25},  # high mountain, rain-shadow, barani-like — LOW
    "Buner": {"province": "Khyber Pakhtunkhwa", "lat": 34.4330, "lon": 72.5580, "temp_offset_c": -2.0, "monsoon_strength": 0.60, "humidity_offset": 2, "canal_flow_baseline_cusecs": 110, "river_exposure": 0.3},  # hilly — low-moderate
    "Shangla": {"province": "Khyber Pakhtunkhwa", "lat": 34.8990, "lon": 72.6690, "temp_offset_c": -4.5, "monsoon_strength": 0.55, "humidity_offset": 2, "canal_flow_baseline_cusecs": 70, "river_exposure": 0.25},  # mountainous — LOW
    "Malakand": {"province": "Khyber Pakhtunkhwa", "lat": 34.5590, "lon": 71.9310, "temp_offset_c": -1.5, "monsoon_strength": 0.60, "humidity_offset": 2, "canal_flow_baseline_cusecs": 150, "river_exposure": 0.4},  # Swat river valley entrance — moderate
    "Haripur": {"province": "Khyber Pakhtunkhwa", "lat": 33.9960, "lon": 72.9330, "temp_offset_c": -3.0, "monsoon_strength": 0.68, "humidity_offset": 3, "canal_flow_baseline_cusecs": 130, "river_exposure": 0.6},  # hosts Tarbela Dam on the Indus — moderate-high
    "Mansehra": {"province": "Khyber Pakhtunkhwa", "lat": 34.3300, "lon": 73.2000, "temp_offset_c": -3.8, "monsoon_strength": 0.65, "humidity_offset": 3, "canal_flow_baseline_cusecs": 110, "river_exposure": 0.3},  # hilly — low-moderate
    "Battagram": {"province": "Khyber Pakhtunkhwa", "lat": 34.6790, "lon": 73.0230, "temp_offset_c": -4.2, "monsoon_strength": 0.58, "humidity_offset": 3, "canal_flow_baseline_cusecs": 70, "river_exposure": 0.25},  # mountainous — LOW
    "Kohistan": {"province": "Khyber Pakhtunkhwa", "lat": 35.3820, "lon": 73.0000, "temp_offset_c": -5.5, "monsoon_strength": 0.40, "humidity_offset": 0, "canal_flow_baseline_cusecs": 60, "river_exposure": 0.5},  # Indus gorge terrain, flash-flood prone — moderate
    "Bajaur": {"province": "Khyber Pakhtunkhwa", "lat": 34.6870, "lon": 71.5090, "temp_offset_c": -1.0, "monsoon_strength": 0.45, "humidity_offset": -2, "canal_flow_baseline_cusecs": 90, "river_exposure": 0.3},  # merged tribal district, hilly — low-moderate
    "Khyber": {"province": "Khyber Pakhtunkhwa", "lat": 34.0090, "lon": 71.2170, "temp_offset_c": -0.5, "monsoon_strength": 0.40, "humidity_offset": -3, "canal_flow_baseline_cusecs": 100, "river_exposure": 0.25},  # merged tribal district, hilly (Khyber Pass) — LOW
    "Kurram": {"province": "Khyber Pakhtunkhwa", "lat": 33.8330, "lon": 70.0670, "temp_offset_c": -2.0, "monsoon_strength": 0.35, "humidity_offset": -2, "canal_flow_baseline_cusecs": 110, "river_exposure": 0.4},  # merged tribal district, Kurram river valley — moderate
    "Orakzai": {"province": "Khyber Pakhtunkhwa", "lat": 33.5000, "lon": 70.6500, "temp_offset_c": -1.0, "monsoon_strength": 0.35, "humidity_offset": -3, "canal_flow_baseline_cusecs": 80, "river_exposure": 0.25},  # merged tribal district, hilly — LOW
    "Mohmand": {"province": "Khyber Pakhtunkhwa", "lat": 34.5000, "lon": 71.3830, "temp_offset_c": -0.3, "monsoon_strength": 0.45, "humidity_offset": -2, "canal_flow_baseline_cusecs": 120, "river_exposure": 0.35},  # merged tribal district, near the Kabul river — moderate
    "North Waziristan": {"province": "Khyber Pakhtunkhwa", "lat": 32.9500, "lon": 69.8830, "temp_offset_c": 1.0, "monsoon_strength": 0.25, "humidity_offset": -5, "canal_flow_baseline_cusecs": 90, "river_exposure": 0.4},  # merged tribal district, Kurram/Tochi rivers — moderate
    "South Waziristan": {"province": "Khyber Pakhtunkhwa", "lat": 32.3000, "lon": 69.6000, "temp_offset_c": 1.2, "monsoon_strength": 0.22, "humidity_offset": -5, "canal_flow_baseline_cusecs": 80, "river_exposure": 0.4},  # merged tribal district, Gomal river — moderate

    # --- Balochistan (12) ---------------------------------------------------
    "Quetta": {"province": "Balochistan", "lat": 30.1798, "lon": 66.9750, "temp_offset_c": -4.0, "monsoon_strength": 0.10, "humidity_offset": -8, "canal_flow_baseline_cusecs": 80, "river_exposure": 0.1},  # high altitude, barani, outside monsoon corridor — LOW
    "Khuzdar": {"province": "Balochistan", "lat": 27.8021, "lon": 66.6167, "temp_offset_c": -1.0, "monsoon_strength": 0.12, "humidity_offset": -6, "canal_flow_baseline_cusecs": 90, "river_exposure": 0.15},  # highland — LOW
    "Sibi": {"province": "Balochistan", "lat": 29.5433, "lon": 67.8773, "temp_offset_c": 5.5, "monsoon_strength": 0.15, "humidity_offset": -6, "canal_flow_baseline_cusecs": 200, "river_exposure": 0.35},  # among the hottest places in Pakistan, near the Nari river — moderate
    "Nasirabad": {"province": "Balochistan", "lat": 28.8390, "lon": 68.4270, "temp_offset_c": 4.0, "monsoon_strength": 0.20, "humidity_offset": -3, "canal_flow_baseline_cusecs": 450, "river_exposure": 0.55},  # canal-command plains fed by the Indus (Kachhi canal) — moderate-high
    "Kech": {"province": "Balochistan", "lat": 26.0031, "lon": 63.0480, "temp_offset_c": 1.5, "monsoon_strength": 0.05, "humidity_offset": 8, "canal_flow_baseline_cusecs": 110, "river_exposure": 0.15},  # Makran coast, arid but humid air — LOW
    "Gwadar": {"province": "Balochistan", "lat": 25.1264, "lon": 62.3225, "temp_offset_c": -0.5, "monsoon_strength": 0.03, "humidity_offset": 18, "canal_flow_baseline_cusecs": 60, "river_exposure": 0.1},  # coastal, outside monsoon corridor, barani — LOW
    "Lasbela": {"province": "Balochistan", "lat": 25.8600, "lon": 66.4600, "temp_offset_c": 2.0, "monsoon_strength": 0.10, "humidity_offset": 8, "canal_flow_baseline_cusecs": 180, "river_exposure": 0.35},  # coastal plains, Porali river — moderate
    "Jaffarabad": {"province": "Balochistan", "lat": 28.2800, "lon": 68.2900, "temp_offset_c": 4.5, "monsoon_strength": 0.20, "humidity_offset": -3, "canal_flow_baseline_cusecs": 420, "river_exposure": 0.75},  # Kachhi plains fed by the Indus, severely hit in 2010/2022 floods — HIGH
    "Zhob": {"province": "Balochistan", "lat": 31.3410, "lon": 69.4460, "temp_offset_c": -3.0, "monsoon_strength": 0.15, "humidity_offset": -6, "canal_flow_baseline_cusecs": 90, "river_exposure": 0.3},  # highland, Zhob river valley — low-moderate
    "Loralai": {"province": "Balochistan", "lat": 30.3705, "lon": 68.5978, "temp_offset_c": -2.0, "monsoon_strength": 0.15, "humidity_offset": -6, "canal_flow_baseline_cusecs": 100, "river_exposure": 0.2},  # highland — LOW
    "Panjgur": {"province": "Balochistan", "lat": 26.9700, "lon": 64.0970, "temp_offset_c": 2.0, "monsoon_strength": 0.04, "humidity_offset": -8, "canal_flow_baseline_cusecs": 90, "river_exposure": 0.1},  # arid interior — LOW
    "Chagai": {"province": "Balochistan", "lat": 29.0000, "lon": 64.5000, "temp_offset_c": 1.0, "monsoon_strength": 0.03, "humidity_offset": -10, "canal_flow_baseline_cusecs": 40, "river_exposure": 0.05},  # extreme desert, no river — LOW

    # --- Capital / AJK / GB (6) ---------------------------------------------
    "Islamabad": {"province": "Capital/AJK/GB", "lat": 33.6844, "lon": 73.0479, "temp_offset_c": -1.5, "monsoon_strength": 0.78, "humidity_offset": 2, "canal_flow_baseline_cusecs": 150, "river_exposure": 0.3},  # Soan river tributary — moderate
    "Muzaffarabad": {"province": "Capital/AJK/GB", "lat": 34.3700, "lon": 73.4711, "temp_offset_c": -3.5, "monsoon_strength": 0.70, "humidity_offset": 5, "canal_flow_baseline_cusecs": 100, "river_exposure": 0.65},  # hilly AJK, at the Neelum/Jhelum confluence — moderate-high
    "Gilgit": {"province": "Capital/AJK/GB", "lat": 35.9208, "lon": 74.3144, "temp_offset_c": -8.0, "monsoon_strength": 0.10, "humidity_offset": -5, "canal_flow_baseline_cusecs": 70, "river_exposure": 0.2},  # high mountain, glacier-fed not canal-fed — LOW
    "Mirpur": {"province": "Capital/AJK/GB", "lat": 33.1478, "lon": 73.7517, "temp_offset_c": 0.5, "monsoon_strength": 0.60, "humidity_offset": 3, "canal_flow_baseline_cusecs": 180, "river_exposure": 0.6},  # on the Jhelum, hosts Mangla Dam reservoir — moderate-high
    "Kotli": {"province": "Capital/AJK/GB", "lat": 33.5178, "lon": 73.9027, "temp_offset_c": -1.0, "monsoon_strength": 0.65, "humidity_offset": 4, "canal_flow_baseline_cusecs": 130, "river_exposure": 0.4},  # hilly AJK, Poonch river — moderate
    "Skardu": {"province": "Capital/AJK/GB", "lat": 35.2971, "lon": 75.6333, "temp_offset_c": -9.0, "monsoon_strength": 0.08, "humidity_offset": -6, "canal_flow_baseline_cusecs": 60, "river_exposure": 0.2},  # high mountain, glacier-fed, Karakoram rain shadow — LOW
}


def list_district_names() -> list[str]:
    """All 107 district names, in the fixed order defined above."""
    return list(DISTRICTS.keys())


def districts_by_province() -> dict[str, list[str]]:
    """District names grouped by province, preserving insertion order."""
    grouped: dict[str, list[str]] = {}
    for name, params in DISTRICTS.items():
        grouped.setdefault(params["province"], []).append(name)
    return grouped


# --- District codes (LEHAR Phase 2.5) ---------------------------------------
#
# The flood lead-time model (backend/ml/flood_dl/) needs a filesystem- and
# URL-safe identifier per district, because it writes one data file per
# district (data/flood_history/<code>.parquet) and stores a fixed district
# ordering inside the exported ONNX model's embedding table. District NAMES
# stay the identifier everywhere else in the project (the API, the database's
# district_code column, the alert engine) — these helpers only add a stable
# slug alongside them, they never replace a name.
#
# The slug is lowercase with underscores: "Rahim Yar Khan" -> "rahim_yar_khan".
# All 107 names are plain letters and spaces, so the slugs are unique; a test
# asserts that, because a collision would silently make two districts share
# one data file.


def district_code(name: str) -> str:
    """Filesystem-safe slug for a district name."""
    return "_".join(part for part in name.lower().split() if part)


def district_codes() -> dict[str, str]:
    """{district name: code} for all 107 districts, in the fixed order above."""
    return {name: district_code(name) for name in DISTRICTS}


def district_for_code(code: str) -> str | None:
    """The district name a code belongs to, or None if no district matches."""
    for name in DISTRICTS:
        if district_code(name) == code:
            return name
    return None
