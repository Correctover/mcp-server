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

const NodeBox: React.FC<{
	label: string;
	subtitle?: string;
	width?: number;
	frame: number;
	start: number;
}> = ({label, subtitle, width = 280, frame, start}) => {
	const {fps} = useVideoConfig();
	const local = frame - start;
	const progress = spring({
		fps,
		frame: Math.max(0, local),
		config: {damping: 13, stiffness: 110},
	});
	const opacity = interpolate(local, [0, 12, 24], [0, 0.7, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	return (
		<div
			style={{
				width,
				height: 140,
				borderRadius: 22,
				background: 'rgba(255,255,255,0.04)',
				border: '1px solid rgba(255,255,255,0.1)',
				display: 'flex',
				flexDirection: 'column',
				alignItems: 'center',
				justifyContent: 'center',
				opacity,
				transform: `translateY(${interpolate(progress, [0, 1], [24, 0])}px) scale(${interpolate(
					progress,
					[0, 1],
					[0.94, 1]
				)})`,
				boxShadow: '0 20px 40px rgba(0,0,0,0.18)',
			}}
		>
			<div
				style={{
					fontSize: 38,
					fontWeight: 800,
					letterSpacing: '-0.03em',
					color: white,
				}}
			>
				{label}
			</div>
			{subtitle ? (
				<div
					style={{
						marginTop: 8,
						fontSize: 22,
						color: cyan,
						fontWeight: 600,
					}}
				>
					{subtitle}
				</div>
			) : null}
		</div>
	);
};

const Badge: React.FC<{
	label: string;
	x: number;
	y: number;
	frame: number;
	start: number;
}> = ({label, x, y, frame, start}) => {
	const local = frame - start;
	const opacity = interpolate(local, [0, 12, 24], [0, 0.7, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});
	return (
		<div
			style={{
				position: 'absolute',
				left: x,
				top: y,
				opacity,
				padding: '14px 22px',
				borderRadius: 999,
				background: 'rgba(0,229,255,0.08)',
				border: '1px solid rgba(0,229,255,0.25)',
				color: white,
				fontWeight: 700,
				fontSize: 22,
			}}
		>
			{label}
		</div>
	);
};

export const Scene3: React.FC = () => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();

	const titleOpacity = interpolate(frame, [0, 20], [0, 1], {
		extrapolateRight: 'clamp',
	});

	const flowProgress = spring({
		fps,
		frame: frame - 40,
		config: {damping: 18, stiffness: 90},
	});

	const providerProgress = spring({
		fps,
		frame: frame - 110,
		config: {damping: 16, stiffness: 90},
	});

	const line1 = interpolate(flowProgress, [0, 1], [0, 250]);
	const line2 = interpolate(flowProgress, [0, 1], [0, 300]);
	const providerLineA = interpolate(providerProgress, [0, 1], [0, 170]);
	const providerLineB = interpolate(providerProgress, [0, 1], [0, 170]);
	const providerLineC = interpolate(providerProgress, [0, 1], [0, 170]);

	const shieldOpacity = interpolate(frame, [120, 145], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	return (
		<AbsoluteFill
			style={{
				background: bg,
				fontFamily:
					'-apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif',
				color: white,
			}}
		>
			<div
				style={{
					position: 'absolute',
					inset: 0,
					padding: '80px 100px',
				}}
			>
				<div
					style={{
						fontSize: 88,
						fontWeight: 900,
						letterSpacing: '-0.05em',
						opacity: titleOpacity,
						marginBottom: 50,
					}}
				>
					How It Works
				</div>

				<div
					style={{
						position: 'relative',
						width: '100%',
						height: 700,
					}}
				>
					<div style={{position: 'absolute', left: 70, top: 210}}>
						<NodeBox label="Your App" frame={frame} start={10} />
					</div>

					<div style={{position: 'absolute', left: 520, top: 210}}>
						<NodeBox label="SDK" subtitle="in-process" width={320} frame={frame} start={35} />
					</div>

					<div style={{position: 'absolute', right: 70, top: 70}}>
						<NodeBox label="Provider A" frame={frame} start={120} />
					</div>
					<div style={{position: 'absolute', right: 70, top: 255}}>
						<NodeBox label="Provider B" frame={frame} start={138} />
					</div>
					<div style={{position: 'absolute', right: 70, top: 440}}>
						<NodeBox label="Provider C" frame={frame} start={156} />
					</div>

					<div
						style={{
							position: 'absolute',
							left: 350,
							top: 278,
							width: line1,
							height: 6,
							background: `linear-gradient(90deg, ${cyan}, ${indigo})`,
							borderRadius: 999,
							boxShadow: '0 0 16px rgba(0,229,255,0.35)',
						}}
					/>

					<div
						style={{
							position: 'absolute',
							left: 840,
							top: 278,
							width: line2,
							height: 6,
							background: `linear-gradient(90deg, ${indigo}, ${cyan})`,
							borderRadius: 999,
							boxShadow: '0 0 16px rgba(99,102,241,0.35)',
						}}
					/>

					<div
						style={{
							position: 'absolute',
							left: 905,
							top: 235,
							opacity: shieldOpacity,
							width: 54,
							height: 60,
							clipPath: 'polygon(50% 0%, 90% 15%, 90% 55%, 50% 100%, 10% 55%, 10% 15%)',
							background: `linear-gradient(180deg, ${cyan}, ${indigo})`,
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'center',
							color: bg,
							fontWeight: 900,
							fontSize: 24,
							boxShadow: '0 0 24px rgba(0,229,255,0.3)',
						}}
					>
						✓
					</div>

					<div
						style={{
							position: 'absolute',
							left: 1140,
							top: 145,
							width: providerLineA,
							height: 4,
							background: 'rgba(0,229,255,0.8)',
							transform: 'rotate(-28deg)',
							transformOrigin: 'left center',
							borderRadius: 999,
						}}
					/>
					<div
						style={{
							position: 'absolute',
							left: 1140,
							top: 280,
							width: providerLineB,
							height: 4,
							background: 'rgba(0,229,255,0.8)',
							borderRadius: 999,
						}}
					/>
					<div
						style={{
							position: 'absolute',
							left: 1140,
							top: 415,
							width: providerLineC,
							height: 4,
							background: 'rgba(0,229,255,0.8)',
							transform: 'rotate(28deg)',
							transformOrigin: 'left center',
							borderRadius: 999,
						}}
					/>

					<Badge label="Zero Network Overhead" x={120} y={560} frame={frame} start={170} />
					<Badge label="No Proxy" x={700} y={560} frame={frame} start={188} />
					<Badge label="Open Source" x={1040} y={560} frame={frame} start={206} />
				</div>
			</div>
		</AbsoluteFill>
	);
};
