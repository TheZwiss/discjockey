import { describe, expect, it } from 'vitest';
import { LOGO_KEYS, LOGO_NAMES, SERVICE_LOGOS } from './serviceLogos';

describe('serviceLogos', () => {
  it('has all five services, each with its name', () => {
    expect(LOGO_KEYS).toEqual(['spotify', 'youtube', 'youtubemusic', 'soundcloud', 'qobuz']);
    for (const k of LOGO_KEYS) expect(LOGO_NAMES[k]).toBeTruthy();
    expect(LOGO_NAMES.youtubemusic).toBe('YouTube Music');
  });

  it('draws every logo as one 14 px SVG, hidden from VoiceOver (the mark names it)', () => {
    for (const k of LOGO_KEYS) {
      const svg = SERVICE_LOGOS[k];
      expect(svg.startsWith('<svg width="14" height="14" ')).toBe(true);
      expect(svg).toContain('aria-hidden="true"');
      expect(svg.endsWith('</svg>')).toBe(true);
      expect(svg.match(/<svg/g)).toHaveLength(1);
      expect(svg).not.toMatch(/<script|on\w+=/i);
    }
  });

  it('keeps the services\' own colours', () => {
    expect(SERVICE_LOGOS.spotify).toContain('#1ED760');
    expect(SERVICE_LOGOS.youtube).toContain('#FF0000');
    expect(SERVICE_LOGOS.youtubemusic).toContain('#FF0000');
    expect(SERVICE_LOGOS.soundcloud).toContain('#FF5500');
    // Qobuz: the black tile with its faint edge
    expect(SERVICE_LOGOS.qobuz).toContain('fill="#000" stroke="rgba(255,255,255,.3)"');
  });
});
