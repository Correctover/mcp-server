import React from 'react';
import { Composition } from 'remotion';
import { CorrectoverDemo } from './CorrectoverDemo';

export const RemotionRoot: React.FC = () => {
	return (
		<>
			<Composition
				id="CorrectoverDemo"
				component={CorrectoverDemo}
				durationInFrames={45 * 30} // 45 seconds at 30fps = 1350 frames
				fps={30}
				width={1920}
				height={1080}
			/>
		</>
	);
};
