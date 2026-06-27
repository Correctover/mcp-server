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

const dimensions = [
	'Schema Validation',
	'Semantic Equivalence',
	'Latency Compliance',
	'Cost Guardrails',
	'Content Integrity',
	'Identity Verification',
];

const CheckIcon: React.FC = () => (
	<div
		style={{
			width: 28,
			height: 28,
			borderRadius: 999,
			background: `linear-gradient(135deg, ${cyan}, ${indigo})`,
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'center',
			color: bg,
			fontWeight: 900,
			fontSize: 18,
			boxShadow: `0 0 18px rgba(0,229,255,0.28)`,
			flexShrink: 0,
		}}
	>
		✓
	</div>
);

const DimensionBox: React.FC<{
	frame: number;
	start: number;
	label: string;
}> = ({frame, start, label}) => {
	const {fps} = useVideoConfig();
	const local = frame - start;
	const progress = spring({
		fps,
		frame: Math.max(0, local),
		config: {damping: 14, stiffness: 120},
	});
	const opacity = interpolate(local, [0, 8, 20], [0, 0.7, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	return (
		<div
			style={{
				opacity,
				transform: `translateY(${interpolate(progress, [0, 1], [40, 0])}px) scale(${interpolate(
					progress,
					[0, 1],
					[0.95, 1]
				)})`,
				background: 'rgba(255,255,255,0.04)',
				border: '1px solid rgba(255,255,255,0.1)',
				borderRadius: 20,
				padding: '28px 30px',
				display: 'flex',
				alignItems: 'center',
				gap: 18,
				boxShadow: '0 10px 30px rgba(0,0,0,0.18)',
				backdropFilter: 'blur(6px)',
			}}
		>
			<CheckIcon />
			<div
				style={{
					color: white,
					fontSize: 34,
					fontWeight: 700,
					letterSpacing: '-0.02em',
				}}
			>
				{label}
			</div>
		</div>
	);
};

export const Scene2: React.FC = () => {
	const frame = useCurrentFrame();

	const titleOpacity = interpolate(frame, [0, 24], [0, 1], {
		extrapolateRight: 'clamp',
	});
	const titleY = interpolate(frame, [0, 24], [30, 0], {
		extrapolateRight: 'clamp',
	});

	const p50 = Math.round(interpolate(frame, [220, 280], [0, 22], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	}));
	const p99 = Math.round(interpolate(frame, [230, 290], [0, 47], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	}));

	const codeOpacity = interpolate(frame, [300, 340], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	return (
		<AbsoluteFill
			style={{
				background: `radial-gradient(circle at top center, rgba(0,229,255,0.08) 0%, rgba(10,10,26,1) 48%), ${bg}`,
				fontFamily:
					'-apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif',
				color: white,
			}}
		>
			<div
				style={{
					position: 'absolute',
					inset: 0,
					padding: '90px 110px',
					display: 'flex',
					flexDirection: 'column',
				}}
			>
				<div
					style={{
						fontSize: 56,
						fontWeight: 700,
						opacity: titleOpacity,
						transform: `translateY(${titleY}px)`,
						letterSpacing: '-0.03em',
					}}
				>
					Correctover:
				</div>
				<div
					style={{
						fontSize: 102,
						fontWeight: 900,
						letterSpacing: '-0.05em',
						marginTop: 8,
						marginBottom: 48,
						opacity: titleOpacity,
						transform: `translateY(${titleY}px)`,
						background: `linear-gradient(90deg, ${cyan}, ${indigo})`,
						WebkitBackgroundClip: 'text',
						WebkitTextFillColor: 'transparent',
					}}
				>
					Verified Failover
				</div>

				<div
					style={{
						display: 'grid',
						gridTemplateColumns: '1fr 1fr',
						gap: 22,
						width: '100%',
					}}
				>
					{dimensions.map((label, i) => (
						<Sequence key={label} from={40 + i * 24} durationInFrames={440 - i * 24}>
							<DimensionBox frame={frame} start={40 + i * 24} label={label} />
						</Sequence>
					))}
				</div>

				<div
					style={{
						marginTop: 44,
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'space-between',
						gap: 40,
					}}
				>
					<div
						style={{
							padding: '22px 28px',
							borderRadius: 18,
							border: '1px solid rgba(0,229,255,0.24)',
							background: 'rgba(0,229,255,0.06)',
							boxShadow: '0 0 24px rgba(0,229,255,0.08)',
						}}
					>
						<div
							style={{
								fontSize: 24,
								opacity: 0.8,
								marginBottom: 8,
							}}
						>
							Benchmark
						</div>
						<div
							style={{
								fontSize: 38,
								fontWeight: 800,
								letterSpacing: '-0.03em',
								color: white,
							}}
						>
							Diagnosis: <span style={{color: cyan}}>P50 {p50}µs</span>{' '}
							<span style={{color: indigo}}>P99 {p99}µs</span>
						</div>
					</div>

					<div
						style={{
							opacity: codeOpacity,
							padding: '22px 28px',
							borderRadius: 18,
							background: 'rgba(99,102,241,0.1)',
							border: '1px solid rgba(99,102,241,0.28)',
							minWidth: 450,
						}}
					>
						<div
							style={{
								fontSize: 18,
								opacity: 0.65,
								marginBottom: 8,
							}}
						>
							Install
						</div>
						<div
							style={{
								fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
								fontSize: 34,
								fontWeight: 700,
								color: cyan,
							}}
						>
							pip install correctover
						</div>
					</div>
				</div>
			</div>
		</AbsoluteFill>
	);
};
