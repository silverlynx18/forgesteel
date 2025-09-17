import { Button, Popover } from 'antd';
import { CloseOutlined, DownOutlined, EditOutlined, ToolOutlined } from '@ant-design/icons';
import { useMemo, useState } from 'react';
import { AppFooter } from '../../panels/app-footer/app-footer';
import { AppHeader } from '../../panels/app-header/app-header';
import { ErrorBoundary } from '../../controls/error-boundary/error-boundary';
import { Monster } from '../../../models/monster';
import { MonsterPanel } from '../../panels/monster-label/monster-label';
import { Options } from '../../../models/options';
import { Playbook } from '../../../models/playbook';
import { RetainerStateModal } from '../../modals/retainer-state/retainer-state-modal';
import { Utils } from '../../../../utils/utils';
import { useNavigation } from '../../../hooks/use-navigation';
import { useParams } from 'react-router';

import './retainer-sheet-page.scss';
import { Sourcebook } from '../../../../models/sourcebook';

interface Props {
	playbook: Playbook;
	options: Options;
	sourcebooks: Sourcebook[];
	highlightAbout: boolean;
	showDirectory: () => void;
	showAbout: () => void;
	showRoll: () => void;
	showReference: () => void;
	persistPlaybook: (playbook: Playbook) => void;
}

export const RetainerSheetPage = (props: Props) => {
	const navigation = useNavigation();
	const { retainerID } = useParams<{ retainerID: string }>();
	const [ showStateModal, setShowStateModal ] = useState<boolean>(false);
	const retainer = useMemo(
		() => props.playbook.retainers.find(r => r.id === retainerID)!,
		[ retainerID, props.playbook.retainers ]
	);

	const onRetainerChanged = (monster: Monster) => {
		const copy = Utils.copy(props.playbook);
		const index = copy.retainers.findIndex(r => r.id === monster.id);
		if (index !== -1) {
			copy.retainers[index] = monster;
		}
		props.persistPlaybook(copy);
	};

	try {
		return (
			<ErrorBoundary>
				<div className='retainer-sheet-page'>
					<AppHeader subheader='Retainer' showDirectory={props.showDirectory}>
						<Button icon={<CloseOutlined />} onClick={() => navigation.goToRetainers()}>
							Close
						</Button>
						<div className='divider' />
						<Button icon={<EditOutlined />} onClick={() => { /* TODO */ }}>
							Edit
						</Button>
						<Button icon={<ToolOutlined />} onClick={() => setShowStateModal(true)}>
							Manage
						</Button>
					</AppHeader>
					<div className='retainer-sheet-page-content'>
						<MonsterPanel monster={retainer} />
					</div>
					<AppFooter page='retainers' highlightAbout={props.highlightAbout} showAbout={props.showAbout} showRoll={props.showRoll} showReference={props.showReference} />
					{
						showStateModal ?
							<RetainerStateModal
								retainer={retainer}
								sourcebooks={props.sourcebooks}
								options={props.options}
								onClose={() => setShowStateModal(false)}
								onChange={onRetainerChanged}
							/>
							: null
					}
				</div>
			</ErrorBoundary>
		);
	} catch (ex) {
		console.error(ex);
		return null;
	}
};
