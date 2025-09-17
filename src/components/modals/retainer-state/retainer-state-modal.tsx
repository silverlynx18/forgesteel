import { AbilitiesPanel } from './abilities-panel';
import { Modal } from '../modal/modal';
import { Monster } from '../../../models/monster';
import { Options } from '../../../models/options';
import { Segmented } from 'antd';
import { Sourcebook } from '../../../models/sourcebook';
import { VitalsPanel } from './vitals-panel';
import { useState } from 'react';

import './retainer-state-modal.scss';

interface Props {
	retainer: Monster;
	sourcebooks: Sourcebook[];
	options: Options;
	onClose: () => void;
	onChange: (monster: Monster) => void;
}

export const RetainerStateModal = (props: Props) => {
	const [ page, setPage ] = useState<string>('Vitals');

	const getContent = () => {
		switch (page) {
			case 'Vitals':
				return (
					<VitalsPanel
						retainer={props.retainer}
						onChange={props.onChange}
					/>
				);
			case 'Abilities':
				return (
					<AbilitiesPanel
						retainer={props.retainer}
						sourcebooks={props.sourcebooks}
						options={props.options}
					/>
				);
		}
	};

	try {
		return (
			<Modal
				toolbar={
					<div style={{ width: '100%' }}>
						<Segmented
							name='tabs'
							block={true}
							options={[ 'Vitals', 'Abilities' ]}
							value={page}
							onChange={setPage}
						/>
					</div>
				}
				content={
					<div className='retainer-state-modal'>
						{getContent()}
					</div>
				}
				onClose={props.onClose}
			/>
		);
	} catch (ex) {
		console.error(ex);
		return null;
	}
};
