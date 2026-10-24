import { describe, expect, it } from 'vitest';
import Ajv2020 from 'ajv/dist/2020';
import schema from '$fixtures/hub_events.schema.json';
import syncRaw from '$fixtures/hub_events_sync.jsonl?raw';
import stoppedRaw from '$fixtures/hub_events_stopped.jsonl?raw';
import { ACTION_FIELDS, EVENT_FIELDS, EVENT_TYPES, RESULT_FIELDS, TRACK_FIELDS } from './events';

const lines = (raw: string) => raw.split('\n').filter((l) => l.trim()).map((l) => JSON.parse(l));
const streams = { sync: lines(syncRaw), stopped: lines(stoppedRaw) };
const all = [...streams.sync, ...streams.stopped];

describe('event schema', () => {
  it('every fixture line validates against hub_events.schema.json', () => {
    const validate = new Ajv2020({ strict: false }).compile(schema);
    for (const [name, evs] of Object.entries(streams)) {
      evs.forEach((e, i) => {
        const ok = validate(e);
        expect(ok, `${name} line ${i + 1}: ${JSON.stringify(validate.errors)}`).toBe(true);
      });
    }
  });
  it('EVENT_TYPES equals the oneOf names in order', () => {
    const names = (schema as any).oneOf.map((o: any) => o.$ref.split('/').pop());
    expect([...EVENT_TYPES]).toEqual(names);
  });
  it('EVENT_FIELDS matches the schema properties of every event type', () => {
    for (const t of EVENT_TYPES) {
      expect([...EVENT_FIELDS[t]].sort(), t).toEqual(Object.keys((schema as any).$defs[t].properties).sort());
    }
    const defs = (schema as any).$defs;
    expect([...ACTION_FIELDS].sort()).toEqual(Object.keys(defs.Action.properties).sort());
    expect([...TRACK_FIELDS].sort()).toEqual(Object.keys(defs.SourceTrack.properties).sort());
    expect([...RESULT_FIELDS].sort()).toEqual(Object.keys(defs.Result.properties).sort());
  });
  it('the keys in the fixtures are a subset of EVENT_FIELDS', () => {
    for (const e of all) {
      const known = EVENT_FIELDS[e.type as keyof typeof EVENT_FIELDS] as readonly string[];
      expect(known, e.type).toBeDefined();
      for (const k of Object.keys(e)) expect(known, `${e.type}.${k}`).toContain(k);
      if (e.action) for (const k of Object.keys(e.action)) expect(ACTION_FIELDS as readonly string[]).toContain(k);
      if (e.action?.track) for (const k of Object.keys(e.action.track)) expect(TRACK_FIELDS as readonly string[]).toContain(k);
      if (e.type === 'ActionFinished') for (const k of Object.keys(e.result)) expect(RESULT_FIELDS as readonly string[]).toContain(k);
    }
  });
});
