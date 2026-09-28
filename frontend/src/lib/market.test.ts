/**
 * Market derivation.
 *
 * The rules here are the difference between honest localization and invented
 * localization, so they are pinned precisely: a value with no assertion is not
 * "inferred", an assertion with no value is not "known", and a campaign with no
 * region is not a market called "Unknown".
 */

import { describe, expect, it } from 'vitest';
import {
  allUnrecorded,
  confidenceCaution,
  creativeImplication,
  groupByMarket,
  hasMarket,
  localCues,
  marketFacts,
} from '@/lib/market';
import type { CampaignSpecification, FieldAssertion } from '@/lib/api';

function assertion(over: Partial<FieldAssertion>): FieldAssertion {
  return {
    field: 'region',
    availability: 'known',
    certainty: 'stated',
    source: null,
    edited_by_human: false,
    ...over,
  };
}

function spec(over: Partial<CampaignSpecification> = {}): CampaignSpecification {
  return {
    region: 'Jaipur, Rajasthan',
    language: 'Hindi + English',
    timing_occasion: 'Hot season, March to June',
    audience: 'University students, 18–24',
    audience_insight: null,
    required_elements: [],
    avoid_restrictions: [],
    field_assertions: {},
    ...over,
  } as CampaignSpecification;
}

const byKey = (facts: ReturnType<typeof marketFacts>) =>
  new Map(facts.map((f) => [f.key, f]));

describe('market facts', () => {
  it('reads the place, language and season the specification holds', () => {
    const facts = byKey(marketFacts(spec()));
    expect(facts.get('region')?.value).toBe('Jaipur, Rajasthan');
    expect(facts.get('language')?.value).toBe('Hindi + English');
    expect(facts.get('timing_occasion')?.value).toBe('Hot season, March to June');
  });

  it('never splits a region into parts the domain does not have', () => {
    // `region` is one free-text string. Parsing "Jaipur, Rajasthan" into city
    // and state would invent structure the schema never promised.
    const facts = byKey(marketFacts(spec({ region: 'West Bengal and Bihar' })));
    expect(facts.get('region')?.value).toBe('West Bengal and Bihar');
  });

  it('reports every field as unknown when there is no specification', () => {
    // A campaign in discovery. Saying "not known yet" five times is the truth
    // about it; rendering nothing would imply there is nothing to know.
    const facts = marketFacts(null);
    expect(facts).toHaveLength(5);
    for (const fact of facts) {
      expect(fact.value).toBeNull();
      expect(fact.confidence).toBe('unknown');
    }
    expect(hasMarket(facts)).toBe(false);
  });

  it('calls a stated fact stated, and an inferred one inferred', () => {
    const facts = byKey(
      marketFacts(
        spec({
          field_assertions: {
            region: assertion({ certainty: 'stated' }),
            audience: assertion({ field: 'audience', certainty: 'inferred' }),
            language: assertion({ field: 'language', certainty: 'brand_default' }),
          },
        }),
      ),
    );
    expect(facts.get('region')?.confidence).toBe('stated');
    expect(facts.get('audience')?.confidence).toBe('inferred');
    expect(facts.get('language')?.confidence).toBe('brand');
  });

  it('does not promote an unexplained value into a guess', () => {
    // The benchmark seeds specifications directly, so they carry no
    // `field_assertions`. Those values are recorded, not inferred — reporting
    // them as inferred would attribute a guess the system never made.
    const facts = byKey(marketFacts(spec({ field_assertions: {} })));
    expect(facts.get('region')?.confidence).toBe('unrecorded');
    expect(facts.get('region')?.value).toBe('Jaipur, Rajasthan');
  });

  it('treats an unresolved assertion as recorded, not asserted', () => {
    const facts = byKey(
      marketFacts(spec({ field_assertions: { region: assertion({ certainty: 'unresolved' }) } })),
    );
    expect(facts.get('region')?.confidence).toBe('unrecorded');
  });

  it('trusts no assertion over a missing value', () => {
    // An assertion claiming `known` for a field that is empty is still nothing
    // to show. The value decides.
    const facts = byKey(
      marketFacts(spec({ region: null, field_assertions: { region: assertion({}) } })),
    );
    expect(facts.get('region')?.value).toBeNull();
    expect(facts.get('region')?.confidence).toBe('unknown');
  });

  it('treats whitespace as absence', () => {
    const facts = byKey(marketFacts(spec({ region: '   ' })));
    expect(facts.get('region')?.confidence).toBe('unknown');
  });

  it('reports unknown when the assertion says the field is not available', () => {
    const facts = byKey(
      marketFacts(
        spec({ field_assertions: { region: assertion({ availability: 'not_applicable' }) } }),
      ),
    );
    expect(facts.get('region')?.confidence).toBe('unknown');
  });
});

describe('local cues', () => {
  it('surfaces what the creative must include and must avoid', () => {
    const { required, avoid } = localCues(
      spec({
        required_elements: ['finished dish as served'],
        avoid_restrictions: ['tea gardens', 'Bihu costume'],
      }),
    );
    expect(required).toEqual(['finished dish as served']);
    expect(avoid).toEqual(['tea gardens', 'Bihu costume']);
  });

  it('returns empty lists rather than null for a campaign with no specification', () => {
    expect(localCues(null)).toEqual({ required: [], avoid: [] });
  });
});

describe('grouping campaigns by market', () => {
  it('counts campaigns per region without inventing a number', () => {
    const groups = groupByMarket([
      { campaignId: 'a', specification: spec({ region: 'Jaipur, Rajasthan' }) },
      { campaignId: 'b', specification: spec({ region: 'Jaipur, Rajasthan' }) },
      { campaignId: 'c', specification: spec({ region: 'Kochi, Kerala' }) },
    ]);
    expect(groups).toHaveLength(2);
    expect(groups[0]).toMatchObject({ region: 'Jaipur, Rajasthan' });
    expect(groups[0]!.campaignIds).toEqual(['a', 'b']);
  });

  it('omits a campaign with no region instead of bucketing it as unknown', () => {
    // An "Unknown" market would put a pin on the map for a campaign whose
    // place has simply not been decided.
    const groups = groupByMarket([
      { campaignId: 'a', specification: spec({ region: null }) },
      { campaignId: 'b', specification: null },
      { campaignId: 'c', specification: spec({ region: 'Assam' }) },
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0]!.region).toBe('Assam');
  });

  it('collects the distinct languages and audiences seen in a region', () => {
    const groups = groupByMarket([
      { campaignId: 'a', specification: spec({ region: 'Assam', language: 'Assamese' }) },
      { campaignId: 'b', specification: spec({ region: 'Assam', language: 'Assamese' }) },
      { campaignId: 'c', specification: spec({ region: 'Assam', language: 'Hindi' }) },
    ]);
    expect(groups[0]!.languages).toEqual(['Assamese', 'Hindi']);
  });

  it('orders busiest first, then alphabetically, so the list is stable', () => {
    // Requests resolve in an unpredictable order; the rendering must not.
    const groups = groupByMarket([
      { campaignId: 'a', specification: spec({ region: 'Kochi' }) },
      { campaignId: 'b', specification: spec({ region: 'Assam' }) },
      { campaignId: 'c', specification: spec({ region: 'Assam' }) },
      { campaignId: 'd', specification: spec({ region: 'Bengaluru' }) },
    ]);
    expect(groups.map((g) => g.region)).toEqual(['Assam', 'Bengaluru', 'Kochi']);
  });

  it('returns nothing for no campaigns', () => {
    expect(groupByMarket([])).toEqual([]);
  });
});

// ------------------------------------------------------- creative implication

describe('creative implication', () => {
  it('says what a known place asks of the work', () => {
    const [region] = marketFacts(spec());
    expect(creativeImplication(region!)).toContain('Jaipur, Rajasthan');
  });

  it('gives no instruction for a fact nobody has decided', () => {
    // Guidance derived from a blank field is how a campaign ends up
    // "localized" for nowhere.
    const facts = byKey(marketFacts(spec({ region: null })));
    expect(creativeImplication(facts.get('region')!)).toBeNull();
  });

  it('does not produce a double full stop when the value already ends in one', () => {
    // Specification fields are written as prose. "…several times a week.."
    // is the bug this prevents.
    const facts = byKey(marketFacts(spec({ region: 'Assam.' })));
    expect(creativeImplication(facts.get('region')!)).not.toContain('..');
  });

  it('stops quoting a long value back at the reader', () => {
    const long = 'Family grocery buyers across Assam, 25-55, cooking freshwater fish and vegetable curry several times a week';
    const facts = byKey(marketFacts(spec({ audience: long })));
    const implication = creativeImplication(facts.get('audience')!)!;
    expect(implication).not.toContain(long);
    expect(implication).toContain('these people');
  });

  it('cautions about an inferred fact but not a stated one', () => {
    expect(confidenceCaution('inferred')).toMatch(/confirming/i);
    expect(confidenceCaution('stated')).toBeNull();
    expect(confidenceCaution('unknown')).toMatch(/not known/i);
  });

  it('says nothing per-row when a value simply has no recorded source', () => {
    // The common case for a directly-written specification. Repeating it on
    // every row is noise; the screen says it once for the whole set.
    expect(confidenceCaution('unrecorded')).toBeNull();
  });

  it('detects a specification that records no sources at all', () => {
    expect(allUnrecorded(marketFacts(spec({ field_assertions: {} })))).toBe(true);
    expect(
      allUnrecorded(
        marketFacts(spec({ field_assertions: { region: assertion({ certainty: 'stated' }) } })),
      ),
    ).toBe(false);
    // Nothing known at all is not "all unrecorded" — it is empty.
    expect(allUnrecorded(marketFacts(null))).toBe(false);
  });
});
