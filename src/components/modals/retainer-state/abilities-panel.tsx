import { Button, Drawer } from 'antd';
import { Ability } from '../../../models/ability';
import { AbilityPanel } from '../../panels/ability-info/ability-info';
import { ErrorBoundary } from '../../controls/error-boundary/error-boundary';
import { Monster } from '../../../models/monster';
import { MonsterLogic } from '../../../logic/monster-logic';
import { Options } from '../../../models/options';
import { RollModal } from '../roll/roll-modal';
import { Sourcebook } from '../../../models/sourcebook';
import { useState } from 'react';

interface Props {
	retainer: Monster;
	sourcebooks: Sourcebook[];
	options: Options;
}

export const AbilitiesPanel = (props: Props) => {
	const [ roll, setRoll ] = useState<Ability | null>(null);

	const abilities = MonsterLogic.getAbilities(props.retainer, props.sourcebooks);

	return (
		<ErrorBoundary>
			<div className='abilities-panel'>
				{abilities.map(ability => (
					<AbilityPanel
						key={ability.id}
						ability={ability}
						options={props.options}
						actions={
							<Button onClick={() => setRoll(ability)}>
								Roll
							</Button>
						}
					/>
				))}
			</div>
			<Drawer open={roll !== null} onClose={() => setRoll(null)} closeIcon={null} width='500px'>
				<RollModal
					monster={props.retainer}
					ability={roll!}
					onClose={() => setRoll(null)}
				/>
			</Drawer>
		</ErrorBoundary>
	);
};
