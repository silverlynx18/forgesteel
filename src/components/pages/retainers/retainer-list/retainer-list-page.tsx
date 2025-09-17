import { Button, Checkbox, Input, Popover } from 'antd';
import { DownOutlined, PlusOutlined, SearchOutlined, UserOutlined } from '@ant-design/icons';
import { AppFooter } from '../../../panels/app-footer/app-footer';
import { AppHeader } from '../../../panels/app-header/app-header';
import { Collections } from '../../../../utils/collections';
import { Empty } from '../../../controls/empty/empty';
import { ErrorBoundary } from '../../../controls/error-boundary/error-boundary';
import { Hero } from '../../../../models/hero';
import { Monster } from '../../../../models/monster';
import { Options } from '../../../../models/options';
import { Playbook } from '../../../../models/playbook';
import { SelectablePanel } from '../../../controls/selectable-panel/selectable-panel';
import { Sourcebook } from '../../../../models/sourcebook';
import { Utils } from '../../../../utils/utils';
import { useNavigation } from '../../../../hooks/use-navigation';
import { useState } from 'react';

import './retainer-list-page.scss';

interface Props {
	playbook: Playbook;
	heroes: Hero[];
	sourcebooks: Sourcebook[];
	options: Options;
	highlightAbout: boolean;
	showDirectory: () => void;
	showAbout: () => void;
	showRoll: () => void;
	showReference: () => void;
	addRetainer: () => void;
	persistHero: (hero: Hero) => void;
}

export const RetainerListPage = (props: Props) => {
	const navigation = useNavigation();
	const [ searchTerm, setSearchTerm ] = useState<string>('');

	const getRetainers = () => {
		return props.playbook.retainers
			.filter(r => Utils.textMatches([
				r.name,
			], searchTerm));
	};

	const setMentors = (retainer: Monster, hero: Hero, isMentor: boolean) => {
		const copy = Utils.copy(hero);
		if (isMentor) {
			copy.retainerIDs.push(retainer.id);
		} else {
			copy.retainerIDs = copy.retainerIDs.filter(id => id !== retainer.id);
		}
		props.persistHero(copy);
	};

	const getRetainersSection = (list: Monster[]) => {
		if (list.length === 0) {
			return (
				<Empty />
			);
		}

		return (
			<div className='hero-section-row'>
				{
					list.map(retainer => (
						<SelectablePanel
							key={retainer.id}
							watermark={retainer.picture || undefined}
							onSelect={() => navigation.goToRetainerSheet(retainer.id)}
							footer={
								<Popover
									trigger='click'
									content={
										<div className='mentor-popover'>
											{props.heroes.map(hero => (
												<Checkbox
													key={hero.id}
													checked={hero.retainerIDs.includes(retainer.id)}
													onChange={e => setMentors(retainer, hero, e.target.checked)}
												>
													{hero.name}
												</Checkbox>
											))}
										</div>
									}
								>
									<Button icon={<UserOutlined />}>
										Mentors
									</Button>
								</Popover>
							}
						>
							<div className='name'>{retainer.name}</div>
							<div className='mentors'>
								{props.heroes.filter(h => h.retainerIDs.includes(retainer.id)).map(h => h.name).join(', ')}
							</div>
						</SelectablePanel>
					))
				}
			</div>
		);
	};

	try {
		return (
			<ErrorBoundary>
				<div className='retainer-list-page'>
					<AppHeader subheader='Retainers' showDirectory={props.showDirectory}>
						<Input
							name='search'
							placeholder='Search'
							allowClear={true}
							value={searchTerm}
							suffix={<SearchOutlined />}
							onChange={e => setSearchTerm(e.target.value)}
						/>
						<div className='divider' />
						<Popover
							trigger='click'
							content={(
								<div style={{ width: '500px' }}>
									<Button type='primary' block={true} icon={<PlusOutlined />} onClick={() => props.addRetainer()}>
										Add a New Retainer
									</Button>
								</div>
							)}
						>
							<Button type='primary'>
								Add
								<DownOutlined />
							</Button>
						</Popover>
					</AppHeader>
					<div className='retainer-list-page-content'>
						{getRetainersSection(getRetainers())}
					</div>
					<AppFooter page='retainers' highlightAbout={props.highlightAbout} showAbout={props.showAbout} showRoll={props.showRoll} showReference={props.showReference} />
				</div>
			</ErrorBoundary>
		);
	} catch (ex) {
		console.error(ex);
		return null;
	}
};
