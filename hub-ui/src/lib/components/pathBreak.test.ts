import { describe, expect, it } from 'vitest';
import { pathSegments } from './pathBreak';

describe('pathSegments', () => {
  it('breaks after each slash and keeps the slash with its folder', () => {
    expect(pathSegments('Library/Hard_Bounce/Nachtfalter – Sunrise Tekk')).toEqual(
      ['Library/', 'Hard_Bounce/', 'Nachtfalter – Sunrise Tekk']);
  });
  it('never breaks inside a name, spaces included', () => {
    expect(pathSegments('Library/Armin Hermann - Get Naughty.wav')).toEqual(['Library/', 'Armin Hermann - Get Naughty.wav']);
  });
  it('lets a drive path break after the arrow, never before it', () => {
    expect(pathSegments('Example Drive › Music/Sets')).toEqual(['Example Drive › ', 'Music/', 'Sets']);
    expect(pathSegments('Example Drive › Music/Sets')).toEqual(['Example Drive › ', 'Music/', 'Sets']);
  });
  it('joins back to the path, and handles a leading slash, a trailing slash and an empty path', () => {
    for (const p of ['/Volumes/DJ/Sets/', '~/Music/Old', 'name.wav', '']) expect(pathSegments(p).join('')).toBe(p);
    expect(pathSegments('/a/b')).toEqual(['/', 'a/', 'b']);
    expect(pathSegments('')).toEqual([]);
  });
});
