// Accessibility wiring of Surface and ListRow, rendered on the server (no DOM needed): the names, roles and
// descriptions a screen reader gets, which screenshots can't show.
import { describe, expect, it } from 'vitest';
import { createRawSnippet } from 'svelte';
import { render } from 'svelte/server';
import ListRow from './ListRow.svelte';
import NoteCard from './NoteCard.svelte';
import Surface from './Surface.svelte';

const html = (text: string) => createRawSnippet(() => ({ render: () => `<span>${text}</span>` }));
const attr = (body: string, name: string, tag?: string) => {
  const scope = tag ? body.match(new RegExp(`<${tag}\\b[^>]*>`))?.[0] ?? '' : body;
  return scope.match(new RegExp(`\\s${name}="([^"]*)"`))?.[1];
};

describe('Surface', () => {
  it('is a group named by its visible caption, not a landmark', () => {
    const { body } = render(Surface, { props: { label: 'Playlists', children: html('rows') } });
    expect(body).not.toContain('<section');
    expect(attr(body, 'role', 'div')).toBe('group');
    const id = attr(body, 'aria-labelledby', 'div');
    expect(id).toBeTruthy();
    expect(body).toMatch(new RegExp(`id="${id}"[^>]*>Playlists<`));
  });

  it('has no role or name without a label', () => {
    const { body } = render(Surface, { props: { children: html('rows') } });
    expect(attr(body, 'role', 'div')).toBeUndefined();
    expect(attr(body, 'aria-labelledby', 'div')).toBeUndefined();
  });

  it("lets the caller's role and aria-labelledby win", () => {
    const { body } = render(Surface, { props: { label: 'X', role: 'region', 'aria-labelledby': 'mine', children: html('') } });
    expect(attr(body, 'role', 'div')).toBe('region');
    expect(attr(body, 'aria-labelledby', 'div')).toBe('mine');
  });

  it('keeps NoteCard a note', () => {
    const { body } = render(NoteCard, { props: { tone: 'warn', children: html('Downloads start tomorrow') } });
    expect(attr(body, 'role', 'div')).toBe('note');
  });
});

describe('ListRow', () => {
  it("names its button by the name line only; sub and optional describe it", () => {
    const { body } = render(ListRow, { props: { name: html('Artist – Title'), sub: html('Hard_Bounce'),
      optional: html('new'), checked: true, onclick: () => {} } });
    const button = body.match(/<button\b[^>]*>/)?.[0] ?? '';
    expect(attr(button, 'role')).toBe('checkbox');
    expect(attr(button, 'aria-checked')).toBe('true');
    const named = attr(button, 'aria-labelledby');
    expect(body).toMatch(new RegExp(`id="${named}"[^>]*><span>Artist – Title<`));
    const described = attr(button, 'aria-describedby')?.split(' ') ?? [];
    expect(described).toHaveLength(2);
    expect(body).toMatch(new RegExp(`id="${described[0]}"[^>]*><span>Hard_Bounce<`));
    expect(body).toMatch(new RegExp(`id="${described[1]}"[^>]*><span>new<`));
  });

  it('has no button without onclick, and a row with a second line is tall', () => {
    const { body } = render(ListRow, { props: { name: html('Not found anywhere'), sub: html('Searched everywhere') } });
    expect(body).not.toContain('<button');
    expect(attr(body, 'class', 'div')).toMatch(/\btall\b/);
    const plain = render(ListRow, { props: { name: html('One line') } }).body;
    expect(attr(plain, 'class', 'div')).not.toMatch(/\btall\b/);
  });

  it('marks a selected row current and a disabled row aria-disabled', () => {
    const { body } = render(ListRow, { props: { name: html('A'), selected: true, disabled: true, onclick: () => {} } });
    const button = body.match(/<button\b[^>]*>/)?.[0] ?? '';
    expect(attr(button, 'aria-current')).toBe('true');
    expect(attr(button, 'aria-disabled')).toBe('true');
    expect(attr(button, 'role')).toBeUndefined();
  });
});
