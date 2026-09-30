/*---------------------------------------------------------------------------------------------
 *  Copyright (c) Microsoft Corporation. All rights reserved.
 *  Licensed under the MIT License. See License.txt in the project root for license information.
 *--------------------------------------------------------------------------------------------*/

const viewer = document.getElementById('viewer');
const stlUri = viewer && viewer.dataset.stl;
const threeUri = viewer && viewer.dataset.three;

if (stlUri && threeUri) {
	const THREE = await import(threeUri);
	const canvas = document.createElement('canvas');
	document.body.appendChild(canvas);
	const renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true });
	const scene = new THREE.Scene();
	const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100000);
	scene.add(new THREE.AmbientLight(0xffffff, 0.65));
	const sun = new THREE.DirectionalLight(0xffffff, 0.9);
	sun.position.set(1, 2, 1);
	scene.add(sun);

	let distance = 2000;
	let azimuth = 0.7;
	let polar = 1.05;
	const target = new THREE.Vector3();

	function placeCamera() {
		camera.position.set(
			target.x + distance * Math.sin(polar) * Math.sin(azimuth),
			target.y + distance * Math.cos(polar),
			target.z + distance * Math.sin(polar) * Math.cos(azimuth),
		);
		camera.lookAt(target);
	}

	function resize() {
		const width = window.innerWidth;
		const height = window.innerHeight;
		renderer.setSize(width, height, false);
		camera.aspect = width / Math.max(height, 1);
		camera.updateProjectionMatrix();
	}

	function frame(object) {
		const box = new THREE.Box3().setFromObject(object);
		const size = new THREE.Vector3();
		box.getSize(size);
		box.getCenter(target);
		distance = Math.max(size.x, size.y, size.z) * 1.8;
		placeCamera();
	}

	function parseBinaryStl(buffer) {
		const view = new DataView(buffer);
		if (buffer.byteLength < 84) {
			return undefined;
		}
		const count = view.getUint32(80, true);
		if (buffer.byteLength !== 84 + count * 50) {
			return undefined;
		}
		const positions = new Float32Array(count * 9);
		let offset = 84;
		let cursor = 0;
		for (let triangle = 0; triangle < count; triangle++) {
			offset += 12;
			for (let component = 0; component < 9; component++) {
				positions[cursor++] = view.getFloat32(offset, true);
				offset += 4;
			}
			offset += 2;
		}
		const geometry = new THREE.BufferGeometry();
		geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
		geometry.computeVertexNormals();
		return geometry;
	}

	window.addEventListener('resize', resize);
	canvas.addEventListener('pointerdown', event => {
		canvas.setPointerCapture(event.pointerId);
		canvas.dataset.dragging = '1';
		canvas.dataset.x = String(event.clientX);
		canvas.dataset.y = String(event.clientY);
	});
	canvas.addEventListener('pointermove', event => {
		if (canvas.dataset.dragging !== '1') {
			return;
		}
		const previousX = Number(canvas.dataset.x);
		const previousY = Number(canvas.dataset.y);
		azimuth -= (event.clientX - previousX) * 0.01;
		polar = Math.min(Math.PI - 0.05, Math.max(0.05, polar + (event.clientY - previousY) * 0.01));
		canvas.dataset.x = String(event.clientX);
		canvas.dataset.y = String(event.clientY);
		placeCamera();
	});
	canvas.addEventListener('pointerup', () => {
		canvas.dataset.dragging = '0';
	});
	canvas.addEventListener('wheel', event => {
		event.preventDefault();
		distance = Math.max(10, distance * (event.deltaY > 0 ? 1.08 : 0.92));
		placeCamera();
	}, { passive: false });

	function draw() {
		renderer.render(scene, camera);
		requestAnimationFrame(draw);
	}

	resize();
	placeCamera();
	draw();

	const response = await fetch(stlUri);
	const geometry = parseBinaryStl(await response.arrayBuffer());
	if (geometry) {
		const material = new THREE.MeshStandardMaterial({ color: 0xc4b8a5, metalness: 0.15, roughness: 0.6 });
		const mesh = new THREE.Mesh(geometry, material);
		mesh.rotation.x = -Math.PI / 2;
		scene.add(mesh);
		frame(mesh);
	}
}
