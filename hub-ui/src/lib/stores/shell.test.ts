import { get } from 'svelte/store';
import { describe, expect, it } from 'vitest';
import { bannersSaidInBody, sayInBody } from './shell';

describe('banners said in the body', () => {
  it('is empty until a view says something', () => expect(get(bannersSaidInBody)).toEqual({}));
  it('holds what the view says and clears when it goes', () => {
    const leave = sayInBody({ console: true, readStatus: false });
    expect(get(bannersSaidInBody)).toEqual({ console: true, readStatus: false });
    leave();
    expect(get(bannersSaidInBody)).toEqual({});
  });
  it("keeps the next view's claim when the last view clears after it", () => {
    const leaveOld = sayInBody({ console: true });
    const leaveNew = sayInBody({ readStatus: true });
    leaveOld();
    expect(get(bannersSaidInBody)).toEqual({ readStatus: true });
    leaveNew();
    expect(get(bannersSaidInBody)).toEqual({});
  });
});
