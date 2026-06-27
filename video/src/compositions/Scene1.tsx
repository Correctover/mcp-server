import React from 'react';
import {
	AbsoluteFill,
	Sequence,
	interpolate,
	spring,
	useCurrentFrame,
	useVideoConfig,
} from 'remotion';

const bg = '#0A0A1A';
const cyan = '#00E5FF';
const indigo = '#6366F1';
const white = '#FFFFFF';
const green = '#22C55E';
const red = '#FF4D4F';
const amber = '#F59E0B';

const WarningIcon: React.FC<{size?: number}> = ({size = 28}) => {
	return (
		<div
			style={{
				width: size,
				height: size,
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'center',
				color: red,
				fontSize: size,
				fontWeight: 800,
				lineHeight: 1,
			}}
		>
			⚠
		</div>
	);
};

const GridBackground: React.FC<{frame: number}> = ({frame}) => {
	const offset = frame * 0.4;
	return (
		<>
			<div
				style={{
					position: 'absolute',
					inset: 0,
					background:
						'radial-gradient(circle at center, rgba(99,102,241,0.12) 0%, rgba(10,10,26,0) 55%)',
				}}
			/>
			<div
				style={{
					position: 'absolute',
					inset: 0,
					backgroundImage: `
						linear-gradient(rgba(255,255,255,0.05) 1px, transparent 1px),
						linear-gradient(90deg, rgba(255,255,255,0.05) 1px, transparent 1px)
					`,
					backgroundSize: '80px 80px',
					backgroundPosition: `${offset}px ${offset}px`,
					opacity: 0.35,
				}}
			/>
		</>
	);
};

const FailureRow: React.FC<{
	frame: number;
	start: number;
	label: string;
}> = ({frame, start, label}) => {
	const local = frame - start;
	const entrance = spring({
		fps: 30,
		frame: Math.max(0, local),
		config: {damping: 14, stiffness: 120},
	});
	const opacity = interpolate(local, [0, 10, 30], [0, 0.6, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});
	const glow = interpolate(local, [0, 20], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	return (
		<div
			style={{
				opacity,
				transform: `translateX(${interpolate(entrance, [0, 1], [120, 0])}px)`,
				display: 'flex',
				alignItems: 'center',
				gap: 20,
				width: 980,
				padding: '22px 28px',
				borderRadius: 18,
				background: `linear-gradient(90deg, rgba(255,77,79,${0.2 + glow * 0.08}) 0%, rgba(255,77,79,0.08) 100%)`,
				border: '1px solid rgba(255,77,79,0.45)',
				boxShadow: `0 0 ${20 + glow * 20}px rgba(255,77,79,0.18)`,
			}}
		>
			<WarningIcon />
			<div
				style={{
					color: white,
					fontSize: 40,
					fontWeight: 700,
					letterSpacing: '-0.02em',
				}}
			>
				{label}
			</div>
		</div>
	);
};

export const Scene1: React.FC = () => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();

	const titleOpacity = interpolate(frame, [0, 25], [0, 1], {
		extrapolateRight: 'clamp',
	});
	const titleY = interpolate(frame, [0, 25], [40, 0], {
		extrapolateRight: 'clamp',
	});

	const safeScale = spring({
		fps,
		frame: frame - 20,
		config: {damping: 12, stiffness: 90},
	});

	const endOpacity = interpolate(frame, [290, 330, 360], [0, 1, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	return (
		<AbsoluteFill
			style={{
				backgroundColor: bg,
				fontFamily:
					'-apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif',
				color: white,
				overflow: 'hidden',
			}}
		>
			<GridBackground frame={frame} />

			<div
				style={{
					position: 'absolute',
					inset: 0,
					padding: '90px 120px',
					display: 'flex',
					flexDirection: 'column',
				}}
			>
				<div
					style={{
						opacity: titleOpacity,
						transform: `translateY(${titleY}px)`,
						fontSize: 84,
						fontWeight: 800,
						letterSpacing: '-0.04em',
						marginBottom: 28,
					}}
				>
					Your AI Failover is Broken
				</div>

				<div
					style={{
						transform: `scale(${safeScale})`,
						transformOrigin: 'left center',
						fontSize: 120,
						fontWeight: 900,
						color: green,
						letterSpacing: '-0.05em',
						textShadow: '0 0 30px rgba(34,197,94,0.25)',
						marginBottom: 60,
					}}
				>
					HTTP 200 OK
				</div>

				<div
					style={{
						display: 'flex',
						flexDirection: 'column',
						gap: 22,
						marginTop: 20,
					}}
				>
					<Sequence from={90} durationInFrames={270}>
						<FailureRow frame={frame} start={90} label="Silent Model Substitution" />
					</Sequence>
					<Sequence from={140} durationInFrames={220}>
						<FailureRow frame={frame} start={140} label="Semantic Drift" />
					</Sequence>
					<Sequence from={190} durationInFrames={170}>
						<FailureRow frame={frame} start={190} label="Cost Explosion" />
					</Sequence>
					<Sequence from={240} durationInFrames={120}>
						<FailureRow frame={frame} start={240} label="Content Degradation" />
					</Sequence>
				</div>

				<div
					style={{
						marginTop: 'auto',
						opacity: endOpacity,
						alignSelf: 'center',
						padding: '20px 34px',
						borderRadius: 18,
						background: 'rgba(245,158,11,0.12)',
						border: '1px solid rgba(245,158,11,0.4)',
						color: amber,
						fontSize: 54,
						fontWeight: 800,
						letterSpacing: '-0.03em',
						boxShadow: '0 0 32px rgba(245,158,11,0.12)',
					}}
				>
					But HTTP 200 Cannot Catch These
				</div>
			</div>
		</AbsoluteFill>
	);
};
