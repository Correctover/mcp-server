import React from 'react';
import {
	AbsoluteFill,
	interpolate,
	spring,
	useCurrentFrame,
	useVideoConfig,
} from 'remotion';

const bg = '#0A0A1A';
const cyan = '#00E5FF';
const indigo = '#6366F1';
const white = '#FFFFFF';

export const Scene4: React.FC = () => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();

	const titleSpring = spring({
		fps,
		frame: frame,
		config: {damping: 14, stiffness: 90},
	});

	const subtitleOpacity = interpolate(frame, [20, 50], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	const buttonOpacity = interpolate(frame, [45, 80], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	const fadeOut = interpolate(frame, [210, 260, 270], [1, 0.35, 0], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	return (
		<AbsoluteFill
			style={{
				background: `radial-gradient(circle at center, rgba(99,102,241,0.18) 0%, rgba(10,10,26,1) 56%), ${bg}`,
				fontFamily:
					'-apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif',
				color: white,
				opacity: fadeOut,
			}}
		>
			<div
				style={{
					position: 'absolute',
					inset: 0,
					display: 'flex',
					flexDirection: 'column',
					alignItems: 'center',
					justifyContent: 'center',
					padding: '80px 120px',
					textAlign: 'center',
				}}
			>
				<div
					style={{
						fontSize: 86,
						fontWeight: 900,
						letterSpacing: '-0.05em',
						marginBottom: 20,
						transform: `translateY(${interpolate(titleSpring, [0, 1], [30, 0])}px) scale(${interpolate(
							titleSpring,
							[0, 1],
							[0.92, 1]
						)})`,
					}}
				>
					Build Reliable AI
				</div>

				<div
					style={{
						fontSize: 104,
						fontWeight: 900,
						letterSpacing: '-0.06em',
						background: `linear-gradient(90deg, ${cyan}, ${indigo})`,
						WebkitBackgroundClip: 'text',
						WebkitTextFillColor: 'transparent',
						marginBottom: 24,
					}}
				>
					correctover.com
				</div>

				<div
					style={{
						opacity: subtitleOpacity,
						fontSize: 42,
						fontWeight: 600,
						color: white,
						marginBottom: 42,
						letterSpacing: '-0.02em',
					}}
				>
					Verified Failover for LLM Applications
				</div>

				<div
					style={{
						opacity: buttonOpacity,
						padding: '22px 36px',
						borderRadius: 18,
						background: `linear-gradient(90deg, ${cyan}, ${indigo})`,
						color: bg,
						fontSize: 34,
						fontWeight: 900,
						boxShadow: '0 14px 40px rgba(0,229,255,0.22)',
					}}
				>
					pip install correctover
				</div>
			</div>
		</AbsoluteFill>
	);
};
