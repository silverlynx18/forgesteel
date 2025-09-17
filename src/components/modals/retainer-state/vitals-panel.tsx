import { Monster } from '../../../models/monster';
import { MonsterHealthPanel } from '../../panels/health/health-panel';

interface Props {
	retainer: Monster;
	onChange: (monster: Monster) => void;
}

export const VitalsPanel = (props: Props) => {
	return (
		<MonsterHealthPanel
			monster={props.retainer}
			onChange={props.onChange}
		/>
	);
};
