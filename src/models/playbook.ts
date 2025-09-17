import { Adventure } from './adventure';
import { Counter } from './counter';
import { Encounter } from './encounter';
import { Montage } from './montage';
import { Monster } from './monster';
import { Negotiation } from './negotiation';
import { TacticalMap } from './tactical-map';

export interface Playbook {
	adventures: Adventure[];
	encounters: Encounter[];
	negotiations: Negotiation[];
	montages: Montage[];
	tacticalMaps: TacticalMap[];
	counters: Counter[];
	retainers: Monster[];
	playerViewID: string | null;
}

export type PlaybookElementKind = 'adventure' | 'encounter' | 'negotiation' | 'montage' | 'tactical-map';
