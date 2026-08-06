// Shared chart color system for SmartDesk.
// Single source of truth for category/emotion colors and chart chrome so every
// page renders the same category the same way, in both light and dark mode.
// Hues are ordered and validated for categorical (identity) use: adjacent-pair
// CVD separation and normal-vision floors pass in both modes (see dataviz skill).

export type ThemeMode = 'light' | 'dark';

interface Swatch {
  light: string;
  dark: string;
}

// Fixed hue order — never reassign a category to a different slot and never
// cycle/generate new hues for categories beyond this list.
const CATEGORY_SLOTS: Record<string, Swatch> = {
  work: { light: '#2A78D6', dark: '#3987E5' },
  communication: { light: '#EB6834', dark: '#D95926' },
  learn: { light: '#1BAF7A', dark: '#199E70' },
  documentation: { light: '#EDA100', dark: '#C98500' },
  entertainment: { light: '#E87BA4', dark: '#D55181' },
  other: { light: '#008300', dark: '#008300' },
  social_media: { light: '#4A3AA7', dark: '#9085E9' },
  meetings: { light: '#E34948', dark: '#E66767' },
};

// "system" (and anything unrecognized) is deliberately desaturated — it's a
// recessive "not a real activity category" bucket, not a peer identity color,
// so it never competes with the 8 hues above for attention.
const NEUTRAL_SWATCH: Swatch = { light: '#94A3B8', dark: '#94A3B8' };

export const CATEGORY_ORDER = [
  'work',
  'communication',
  'learn',
  'documentation',
  'entertainment',
  'other',
  'social_media',
  'meetings',
  'system',
];

export function getCategoryColor(category: string, mode: ThemeMode): string {
  const slot = CATEGORY_SLOTS[category];
  return slot ? slot[mode] : NEUTRAL_SWATCH[mode];
}

// Emotion states reuse three of the validated hues (all-pairs safe together)
// plus the same neutral bucket for "no strong signal".
const EMOTION_SLOTS: Record<string, Swatch> = {
  calm: { light: '#1BAF7A', dark: '#199E70' },
  focused: { light: '#2A78D6', dark: '#3987E5' },
  stressed: { light: '#D03B3B', dark: '#E66767' },
};

export function getEmotionColor(emotion: string, mode: ThemeMode): string {
  const slot = EMOTION_SLOTS[emotion.toLowerCase()];
  return slot ? slot[mode] : NEUTRAL_SWATCH[mode];
}

export interface ChartChrome {
  grid: string;
  axisText: string;
  tooltipBg: string;
  tooltipBorder: string;
  tooltipText: string;
}

// Recharts renders grid/axis/tooltip colors as plain SVG/inline-style values,
// so they must be resolved per-theme in JS rather than left as light-only hex.
export function getChartChrome(mode: ThemeMode): ChartChrome {
  return mode === 'dark'
    ? {
        grid: '#334155',
        axisText: '#94A3B8',
        tooltipBg: '#1E293B',
        tooltipBorder: '#334155',
        tooltipText: '#F8FAFC',
      }
    : {
        grid: '#F1F5F9',
        axisText: '#94A3B8',
        tooltipBg: '#FFFFFF',
        tooltipBorder: '#E2E8F0',
        tooltipText: '#1E293B',
      };
}
