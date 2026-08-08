import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

function initModelViewer() {
  const stage = document.getElementById('model-stage');
  if (!stage || stage.dataset.initialized === 'true') return;
  stage.dataset.initialized = 'true';
  const source = stage.dataset.src;
  const extension = stage.dataset.ext;
  const materialName = stage.dataset.mtl || '';
  const status = stage.querySelector('.os-viewer-status span:last-child');

  const fail = (reason) => {
    console.error('OpenShare model viewer:', reason);
    const fallback = document.createElement('div');
    fallback.className = 'os-viewer-error';
    const title = document.createElement('strong');
    title.textContent = 'Could not render this 3D model';
    const detail = document.createElement('span');
    detail.textContent = 'Download the original file to open it in a desktop model viewer.';
    const download = document.createElement('a');
    download.href = source;
    download.textContent = 'Open original';
    fallback.append(title, detail, download);
    stage.replaceChildren(fallback);
  };
  const setStatus = (message) => { if (status) status.textContent = message; };
  const updateProgress = (event) => {
    if (event?.lengthComputable) setStatus(`Loading ${extension.toUpperCase()} model… ${Math.round(event.loaded / event.total * 100)}%`);
  };
  const material = () => new THREE.MeshStandardMaterial({
    color: 0x3298ff, roughness: .56, metalness: .14, side: THREE.DoubleSide,
  });

  async function loadObject() {
    if (extension === 'stl') {
      const { STLLoader } = await import('three/addons/loaders/STLLoader.js');
      const geometry = await new Promise((resolve, reject) => new STLLoader().load(source, resolve, updateProgress, reject));
      geometry.center();
      return new THREE.Mesh(geometry, material());
    }
    if (extension === 'obj') {
      const { OBJLoader } = await import('three/addons/loaders/OBJLoader.js');
      const loader = new OBJLoader();
      if (materialName) {
        const { MTLLoader } = await import('three/addons/loaders/MTLLoader.js');
        const base = source.replace(/[^/]+$/, '');
        try {
          const materials = await new Promise((resolve, reject) => new MTLLoader().setPath(base).setResourcePath(base).load(materialName, resolve, undefined, reject));
          materials.preload();
          loader.setMaterials(materials).setPath(base);
          return await new Promise((resolve, reject) => loader.load(source.split('/').pop(), resolve, updateProgress, reject));
        } catch (error) {
          console.warn('OpenShare model material load failed:', error);
        }
      }
      const object = await new Promise((resolve, reject) => loader.load(source, resolve, updateProgress, reject));
      object.traverse((child) => { if (child.isMesh && !child.material) child.material = material(); });
      return object;
    }
    if (extension === 'fbx') {
      const { FBXLoader } = await import('three/addons/loaders/FBXLoader.js');
      return await new Promise((resolve, reject) => new FBXLoader().load(source, resolve, updateProgress, reject));
    }
    if (extension === '3mf') {
      const { ThreeMFLoader } = await import('three/addons/loaders/3MFLoader.js');
      return await new Promise((resolve, reject) => new ThreeMFLoader().load(source, resolve, updateProgress, reject));
    }
    if (extension === 'step' || extension === 'stp') {
      setStatus('Loading STEP model… initializing renderer');
      const occtFactory = (await import('https://cdn.jsdelivr.net/npm/occt-import-js@0.0.22/+esm')).default;
      const occt = await occtFactory();
      const response = await fetch(source);
      if (!response.ok) throw new Error(`Model fetch failed (${response.status})`);
      const result = occt.ReadStepFile(new Uint8Array(await response.arrayBuffer()), null);
      if (!result?.success) throw new Error('STEP parse failed');
      const group = new THREE.Group();
      for (const mesh of result.meshes || []) {
        const positions = mesh.attributes?.position?.array;
        if (!positions?.length) continue;
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
        if (mesh.attributes?.normal?.array) geometry.setAttribute('normal', new THREE.Float32BufferAttribute(mesh.attributes.normal.array, 3));
        else geometry.computeVertexNormals();
        if (mesh.index?.array) geometry.setIndex(mesh.index.array);
        group.add(new THREE.Mesh(geometry, material()));
      }
      if (!group.children.length) throw new Error('STEP file contained no renderable meshes');
      return group;
    }
    throw new Error(`Unsupported 3D extension: ${extension}`);
  }

  (async () => {
    try {
      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x090d14);
      const camera = new THREE.PerspectiveCamera(45, 1, .01, 10000);
      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      stage.append(renderer.domElement);
      scene.add(new THREE.HemisphereLight(0xffffff, 0x172033, 1.4));
      const key = new THREE.DirectionalLight(0xffffff, 1.6);
      key.position.set(5, 8, 6);
      scene.add(key);
      const controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = .1;
      const resize = () => {
        const width = stage.clientWidth || 800;
        const height = stage.clientHeight || 500;
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
        renderer.setSize(width, height, false);
      };
      resize();
      window.addEventListener('resize', resize);
      const object = await loadObject();
      object.traverse((child) => { if (child.isMesh && child.material) child.material.side = THREE.DoubleSide; });
      const bounds = new THREE.Box3().setFromObject(object);
      const size = bounds.getSize(new THREE.Vector3());
      const center = bounds.getCenter(new THREE.Vector3());
      const maxDimension = Math.max(size.x, size.y, size.z, 1);
      const distance = maxDimension / (2 * Math.tan(camera.fov * Math.PI / 360)) * 1.7;
      camera.position.copy(center).add(new THREE.Vector3(distance, distance * .65, distance));
      camera.near = Math.max(.01, distance / 1000);
      camera.far = distance * 100;
      camera.updateProjectionMatrix();
      controls.target.copy(center);
      const grid = new THREE.GridHelper(Math.max(size.x, size.z, 1) * 2, 10, 0x2a3b50, 0x182433);
      grid.position.y = bounds.min.y;
      scene.add(grid, object);
      stage.querySelector('.os-viewer-status')?.remove();
      const animate = () => {
        if (!stage.isConnected) return;
        controls.update();
        renderer.render(scene, camera);
        window.requestAnimationFrame(animate);
      };
      animate();
    } catch (error) { fail(error); }
  })();
}

document.addEventListener('openshare:model-ready', initModelViewer);
initModelViewer();
