/**
 * Frontend Environment Configuration — TEMPLATE
 *
 * Copy this file to env.js and edit as needed:
 *   cp frontend/env.example.js frontend/env.js
 *
 * env.js is gitignored so your local settings are never committed.
 * This file (env.example.js) IS committed as the reference template.
 *
 * How it works:
 *   This script runs before index.html's main module and sets window.ENV.
 *   The main app reads window.ENV for all runtime configuration.
 */
window.ENV = {
  /**
   * Base URL of the Village Pond Planning API.
   *
   * Same-origin default (empty string) works when the frontend is served
   * directly by the FastAPI backend (the normal setup).
   *
   * Change this when running the frontend separately from the API, e.g.:
   *   API_BASE_URL: 'http://localhost:8000'   // local API on different port
   *   API_BASE_URL: 'https://api.example.com' // production deployment
   */
  API_BASE_URL: '',

  /**
   * Leaflet map initial view: [latitude, longitude, zoom].
   * Default centres on central India (Madhya Pradesh / Chhattisgarh region).
   * Adjust to your region of interest.
   */
  MAP_INITIAL_VIEW: [22.5, 80.0, 5],

  /**
   * CartoDB Positron tile layer URL.
   * Change to any valid Leaflet tile URL to use a different base map.
   * Free alternatives:
   *   OpenStreetMap standard: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
   *   Stamen Terrain:         'https://stamen-tiles.a.ssl.fastly.net/terrain/{z}/{x}/{y}.jpg'
   */
  TILE_URL: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
  TILE_ATTRIBUTION: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',

  /**
   * Maximum upload file size displayed in the UI (informational only —
   * the actual limit is enforced server-side via MAX_UPLOAD_MB in .env).
   */
  MAX_UPLOAD_MB: 20,

  /**
   * Wet-season months (0-indexed, Jan=0) used to highlight the rainfall chart.
   * Default: Jun–Sep (monsoon season for most of India).
   * Adjust for your geography (e.g. [10, 11, 0, 1] for southern-hemisphere winter rain).
   */
  WET_SEASON_MONTHS: [5, 6, 7, 8],
};
