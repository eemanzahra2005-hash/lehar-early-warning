/**
 * Hand-authored inline SVG icons (monoline, 24x24, stroke=currentColor).
 * Kept as plain markup strings — no icon font/library, per CLAUDE.md rule 7
 * (vendor everything locally; this has zero external dependency at all).
 */

function svg(inner) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${inner}</svg>`;
}

export const ICONS = {
  dashboard: svg('<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>'),
  predict: svg('<path d="M12 2.5C12 2.5 5.5 10.2 5.5 14.6A6.5 6.5 0 0 0 18.5 14.6C18.5 10.2 12 2.5 12 2.5Z"/>'),
  map: svg('<path d="M9 3 3 5v16l6-2 6 2 6-2V3l-6 2-6-2Z"/><line x1="9" y1="3" x2="9" y2="19"/><line x1="15" y1="5" x2="15" y2="21"/>'),
  analytics: svg('<line x1="4" y1="20" x2="4" y2="12"/><line x1="10" y1="20" x2="10" y2="6"/><line x1="16" y1="20" x2="16" y2="14"/><line x1="20" y1="20" x2="20" y2="9"/>'),
  forecast: svg('<path d="M7 16.5a4 4 0 0 1 .5-7.9 5 5 0 0 1 9.8 1.2A3.5 3.5 0 0 1 17 16.5H7Z"/><line x1="9" y1="19.5" x2="9" y2="21.5"/><line x1="13" y1="19.5" x2="13" y2="21.5"/>'),
  compare: svg('<line x1="8" y1="3" x2="8" y2="21"/><line x1="16" y1="3" x2="16" y2="21"/><path d="M5 7l3-3 3 3"/><path d="M13 17l3 3 3-3"/>'),
  history: svg('<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 16 14"/>'),
  waterSavings: svg('<path d="M12 3C7.5 8.5 5 12.2 5 15a7 7 0 0 0 14 0c0-2.8-2.5-6.5-7-12Z"/><path d="M9.5 14.5l2 2 3-4"/>'),
  explainability: svg('<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>'),
  models: svg('<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/><line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="15" x2="4" y2="15"/><line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="15" x2="23" y2="15"/>'),
  monitoring: svg('<polyline points="3 12 8 12 11 20 14 4 17 12 21 12"/>'),
  reports: svg('<path d="M6 2h9l3 3v17H6Z"/><line x1="9" y1="9" x2="15" y2="9"/><line x1="9" y1="13" x2="15" y2="13"/><line x1="9" y1="17" x2="13" y2="17"/>'),
  settings: svg('<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>'),
  sun: svg('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
  moon: svg('<path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5Z"/>'),
  menu: svg('<line x1="4" y1="7" x2="20" y2="7"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="17" x2="20" y2="17"/>'),
  chevronDown: svg('<polyline points="6 9 12 15 18 9"/>'),
  user: svg('<circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-6 8-6s8 2 8 6"/>'),
  logout: svg('<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>'),
  alertTriangle: svg('<path d="M12 3 2 20h20Z"/><line x1="12" y1="9" x2="12" y2="14"/><line x1="12" y1="17.3" x2="12" y2="17.4"/>'),
  inbox: svg('<path d="M3 12h4l2 3h6l2-3h4"/><path d="M5 12 3 5h18l-2 7"/><path d="M5 12v6a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-6"/>'),
  refresh: svg('<path d="M21 12a9 9 0 1 1-3-6.7"/><polyline points="21 3 21 9 15 9"/>'),
  plus: svg('<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>'),
  trash: svg('<polyline points="3 6 5 6 21 6"/><path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1L5 6"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/>'),
  leaf: svg('<path d="M5 21c0-9 4-16 15-16 0 9-4 16-15 16Z"/><path d="M5 21c3-3 6-7 8-11"/>'),
  checkCircle: svg('<circle cx="12" cy="12" r="9"/><polyline points="8 12 11 15 16 9"/>'),
  xCircle: svg('<circle cx="12" cy="12" r="9"/><line x1="9" y1="9" x2="15" y2="15"/><line x1="15" y1="9" x2="9" y2="15"/>'),
  wind: svg('<path d="M3 8h11a3 3 0 1 0-3-3"/><path d="M3 16h13a3 3 0 1 1-3 3"/>'),
  info: svg('<circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="8.3"/><line x1="12" y1="11" x2="12" y2="16"/>'),
  save: svg('<path d="M5 3h11l5 5v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"/><path d="M9 3v5h6V3"/><rect x="7" y="13" width="10" height="7"/>'),
  thermometer: svg('<path d="M12 14V4a2 2 0 1 0-4 0v10a4 4 0 1 0 4 0Z"/>'),
  percent: svg('<line x1="19" y1="5" x2="5" y2="19"/><circle cx="6.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="17.5" r="2.5"/>'),
  shield: svg('<path d="M12 2 4 5v6c0 5 3.5 8.5 8 11 4.5-2.5 8-6 8-11V5Z"/>'),
  search: svg('<circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>'),
  rain: svg('<path d="M7 14.5a4 4 0 0 1 .5-7.9 5 5 0 0 1 9.8 1.2A3.5 3.5 0 0 1 17 14.5H7Z"/><line x1="8" y1="17.5" x2="7" y2="20"/><line x1="12" y1="17.5" x2="11" y2="20"/><line x1="16" y1="17.5" x2="15" y2="20"/>'),
  download: svg('<path d="M12 3v13"/><polyline points="7 11 12 16 17 11"/><path d="M5 21h14"/>'),
  filter: svg('<path d="M4 5h16l-6 8v6l-4 2v-8Z"/>'),
  droplet: svg('<path d="M12 3C7.5 8.5 5 12.2 5 15a7 7 0 0 0 14 0c0-2.8-2.5-6.5-7-12Z"/>'),
  chat: svg('<path d="M4 5h16v11H8l-4 4Z"/>'),
  send: svg('<line x1="21" y1="3" x2="10" y2="14"/><path d="M21 3 14 21l-3.5-7.5L3 10Z"/>'),
  close: svg('<line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/>'),
  globe: svg('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>'),
  rocket: svg('<path d="M12 2c3 2.2 5 6.3 5 10.2 0 2-.8 3.9-1.8 5.1l-1 3-2.2-2.1-2.2 2.1-1-3C7.8 16.1 7 14.2 7 12.2 7 8.3 9 4.2 12 2Z"/><circle cx="12" cy="10.5" r="1.6"/><path d="M8 17l-2.5 2.5M16 17l2.5 2.5"/>'),
  undo: svg('<path d="M4 10h9a5 5 0 0 1 0 10h-2"/><polyline points="8 5 4 10 8 15"/>'),
  externalLink: svg('<path d="M14 4h6v6"/><line x1="20" y1="4" x2="10" y2="14"/><path d="M9 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>'),
};

export const NAV_ITEMS = [
  { path: '/dashboard', label: 'Dashboard', icon: ICONS.dashboard },
  { path: '/predict', label: 'Predict', icon: ICONS.predict },
  { path: '/map', label: 'Map', icon: ICONS.map },
  { path: '/analytics', label: 'Analytics', icon: ICONS.analytics },
  { path: '/forecast', label: 'Forecast', icon: ICONS.forecast },
  { path: '/compare', label: 'Compare', icon: ICONS.compare },
  { path: '/history', label: 'History', icon: ICONS.history },
  { path: '/water-savings', label: 'Water Savings', icon: ICONS.waterSavings },
  { path: '/explainability', label: 'Explainability', icon: ICONS.explainability },
  { path: '/models', label: 'Models', icon: ICONS.models },
  { path: '/monitoring', label: 'Monitoring', icon: ICONS.monitoring },
  { path: '/reports', label: 'Reports', icon: ICONS.reports },
  { path: '/settings', label: 'Settings', icon: ICONS.settings },
];
