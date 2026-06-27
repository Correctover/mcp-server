import React from 'react';
import { Sequence } from 'remotion';
import { Scene1 } from './compositions/Scene1';
import { Scene2 } from './compositions/Scene2';
import { Scene3 } from './compositions/Scene3';
import { Scene4 } from './compositions/Scene4';

// Scene timing (30fps):
// Scene 1: Problem — 0 to 360 (12s)
// Scene 2: Solution — 360 to 840 (16s)
// Scene 3: Architecture — 840 to 1080 (8s)
// Scene 4: CTA — 1080 to 1350 (9s)
// Total: 1350 frames = 45 seconds

const SCENE_1_END = 360;
const SCENE_2_END = 840;
const SCENE_3_END = 1080;
const TOTAL_FRAMES = 1350;

export const CorrectoverDemo: React.FC = () => {
	return (
		<>
			<Sequence from={0} durationInFrames={SCENE_1_END}>
				<Scene1 />
			</Sequence>
			<Sequence from={SCENE_1_END} durationInFrames={SCENE_2_END - SCENE_1_END}>
				<Scene2 />
			</Sequence>
			<Sequence from={SCENE_2_END} durationInFrames={SCENE_3_END - SCENE_2_END}>
				<Scene3 />
			</Sequence>
			<Sequence from={SCENE_3_END} durationInFrames={TOTAL_FRAMES - SCENE_3_END}>
				<Scene4 />
			</Sequence>
		</>
	);
};
