// The barograph, drawn live with three.js.
//
// The model, its lighting and its textures come from Dashboard/Barograph/model
// (export_web.py writes public/barograph/). Blender works out the soft,
// shadowed, bounced light once and bakes it; this file adds what has to be
// live: reflections that follow the eye, and the moving parts.
//
// Names it relies on in the model: PenArm, Needle, Table. Materials are
// matched by name.

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { HDRLoader } from "three/addons/loaders/HDRLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { Reflector } from "three/addons/objects/Reflector.js";
import { createViewTransform } from "./tonemap";

const ASSETS = `${import.meta.env.BASE_URL}barograph/`;

// Shared with build_barograph.py (millimetres there, metres here).
const PEN_ARM_M = 0.173;
const CHART_GRID_M = 0.09; // 28.0 to 31.0 inHg
const DIAL_RAD_PER_INHG = THREE.MathUtils.degToRad(66);
const LIGHT_SCALE = 2.5; // light.png stores light / LIGHT_SCALE
const TARGET = new THREE.Vector3(0, 0.118, 0);
const EXPOSURE_STOPS = 0.5;
const DESIGN_ASPECT = 16 / 9;

// Blender's +Y is three's -Z, so a turn about Blender's Y is a turn about -Z here.
const ARM_AXIS = new THREE.Vector3(0, 0, -1);
const UP = new THREE.Vector3(0, 1, 0);

// The baked light map already holds all the diffuse light, so the studio image
// must add only reflections, and the occlusion map must dim only reflections.
const LIGHTS_WITHOUT_STUDIO_DIFFUSE = THREE.ShaderChunk.lights_fragment_maps.replace(
  "iblIrradiance += getIBLIrradiance( geometryNormal );",
  "",
);
const OCCLUDE_REFLECTIONS_ONLY = THREE.ShaderChunk.aomap_fragment.replace(
  "reflectedLight.indirectDiffuse *= ambientOcclusion;",
  "",
);

// Who sees what. The main camera sees the glass; the reflection probe and the
// mirror see the studio backdrop instead, which the main camera must not.
const GLASS_LAYER = 1;
const STUDIO_LAYER = 2;
const CASE_CENTRE = new THREE.Vector3(0, 0.17, 0);
const BED_PLATE = { x: 0.262, y: 0.1122, z: 0.134 }; // mirror size, and its height: just above the plate

/** Polished brass as a mirror: the reflection, tinted, whitening at a glancing angle. */
const BRASS_MIRROR = {
  name: "BrassMirror",
  uniforms: { color: { value: null }, tDiffuse: { value: null }, textureMatrix: { value: null } },
  vertexShader: /* glsl */ `
    uniform mat4 textureMatrix;
    varying vec4 vUv;
    varying vec3 vWorld;
    void main() {
      vUv = textureMatrix * vec4( position, 1.0 );
      vec4 world = modelMatrix * vec4( position, 1.0 );
      vWorld = world.xyz;
      gl_Position = projectionMatrix * viewMatrix * world;
    }`,
  fragmentShader: /* glsl */ `
    uniform vec3 color;
    uniform sampler2D tDiffuse;
    varying vec4 vUv;
    varying vec3 vWorld;
    void main() {
      float facing = clamp( normalize( cameraPosition - vWorld ).y, 0.0, 1.0 );
      vec3 fresnel = color + ( 1.0 - color ) * pow( 1.0 - facing, 5.0 );
      gl_FragColor = vec4( texture2DProj( tDiffuse, vUv ).rgb * fresnel, 1.0 );
      #include <tonemapping_fragment>
      #include <colorspace_fragment>
    }`,
};

/** The studio lighting image as a backdrop, for the eyes that should see it. */
function makeStudioBackdrop(env: THREE.Texture): THREE.Mesh {
  const material = new THREE.ShaderMaterial({
    uniforms: { map: { value: env } },
    side: THREE.BackSide,
    depthWrite: false,
    vertexShader: /* glsl */ `
      varying vec3 vDir;
      void main() {
        vDir = ( modelMatrix * vec4( position, 0.0 ) ).xyz;
        gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );
      }`,
    // Same lookup as three's own, with the half turn that lines the image up.
    fragmentShader: /* glsl */ `
      uniform sampler2D map;
      varying vec3 vDir;
      void main() {
        vec3 d = normalize( vDir ) * vec3( -1.0, 1.0, -1.0 );
        vec2 uv = vec2( atan( d.z, d.x ) * 0.15915494 + 0.5, asin( clamp( d.y, -1.0, 1.0 ) ) * 0.31830989 + 0.5 );
        gl_FragColor = vec4( texture2D( map, uv ).rgb, 1.0 );
      }`,
  });
  const backdrop = new THREE.Mesh(new THREE.SphereGeometry(12, 64, 32), material);
  backdrop.layers.set(STUDIO_LAYER);
  backdrop.frustumCulled = false;
  return backdrop;
}

// Fine print (the chart's grid, the dial's figures) is read from a sharper
// level of the texture than the default, which blurs thin lines away.
const SHARP_PRINT = THREE.ShaderChunk.map_fragment.replace(
  "texture2D( map, vMapUv )",
  "texture2D( map, vMapUv, -0.8 )",
);
// Draw at more than the screen's resolution and scale down: it steadies thin
// lines, bevel glints and reflections.
const SUPERSAMPLE = 1.5;

export interface Barograph {
  /** Pose the pen and the dial needle for a sea-level pressure in inHg. */
  setPressure(inHg: number): void;
  dispose(): void;
}

function linear(r: number, g: number, b: number): THREE.Color {
  return new THREE.Color().setRGB(r, g, b, THREE.LinearSRGBColorSpace);
}

async function loadTexture(
  loader: THREE.TextureLoader,
  file: string,
  colour: boolean,
  anisotropy: number,
  uvSet = 0,
): Promise<THREE.Texture> {
  const tex = await loader.loadAsync(ASSETS + file);
  tex.flipY = false; // glTF texture coordinates
  tex.colorSpace = colour ? THREE.SRGBColorSpace : THREE.NoColorSpace;
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.anisotropy = anisotropy;
  tex.channel = uvSet;
  return tex;
}

export async function createBarograph(canvas: HTMLCanvasElement): Promise<Barograph> {
  // The scene is drawn in scene-linear light; `view` turns that into display colours.
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  const drawScale = () => Math.min(renderer.getPixelRatio() * SUPERSAMPLE, 3);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0, 0, 0);

  const textures = new THREE.TextureLoader();
  const aniso = renderer.capabilities.getMaxAnisotropy();
  const [gltf, env, lut, woodDiff, woodNormal, dial, chart, light, occlusion, cloth] = await Promise.all([
    new GLTFLoader().loadAsync(ASSETS + "barograph.glb"),
    new HDRLoader().loadAsync(ASSETS + "studio_env.hdr"),
    textures.loadAsync(ASSETS + "view_lut.png"),
    loadTexture(textures, "wood_diff.jpg", true, aniso),
    loadTexture(textures, "wood_normal.jpg", false, aniso),
    loadTexture(textures, "dial.png", true, aniso),
    loadTexture(textures, "chart_placeholder.png", true, aniso),
    loadTexture(textures, "light.png", true, 1, 1),
    loadTexture(textures, "ao.png", false, 1, 1),
    loadTexture(textures, "table.png", true, aniso),
  ]);

  const view = createViewTransform(lut, EXPOSURE_STOPS);
  const draw = () => {
    renderer.setRenderTarget(view.target);
    renderer.render(scene, camera);
    view.present(renderer);
  };

  // The studio image is laid out for Blender's axes; half a turn lines it up here.
  env.mapping = THREE.EquirectangularReflectionMapping;
  scene.environment = env;
  scene.environmentRotation.y = Math.PI;

  /** A surface whose diffuse light comes from the bake. */
  const baked = <T extends THREE.MeshStandardMaterial>(material: T, print = false): T => {
    material.lightMap = light;
    material.lightMapIntensity = Math.PI * LIGHT_SCALE;
    material.aoMap = occlusion;
    material.onBeforeCompile = (shader) => {
      shader.fragmentShader = shader.fragmentShader
        .replace("#include <lights_fragment_maps>", LIGHTS_WITHOUT_STUDIO_DIFFUSE)
        .replace("#include <aomap_fragment>", OCCLUDE_REFLECTIONS_ONLY);
      if (print) shader.fragmentShader = shader.fragmentShader.replace("#include <map_fragment>", SHARP_PRINT);
    };
    material.customProgramCacheKey = () => (print ? "baked-print" : "baked-diffuse");
    return material;
  };
  // Metal in a crevice mirrors its bright neighbours, so occlusion dims it only a little.
  const metal = (colour: THREE.Color, roughness: number) =>
    new THREE.MeshStandardMaterial({ color: colour, metalness: 1, roughness, aoMap: occlusion, aoMapIntensity: 0.3 });
  // Lacquered wood: the lacquer is the only layer that mirrors anything.
  const woodLook = {
    map: woodDiff,
    normalMap: woodNormal,
    normalScale: new THREE.Vector2(0.6, 0.6),
    roughness: 0.5,
    specularIntensity: 0,
    clearcoat: 1,
    clearcoatRoughness: 0.1,
  };
  const materials: Record<string, THREE.Material> = {
    Wood: baked(new THREE.MeshPhysicalMaterial({ ...woodLook, color: new THREE.Color(1.25, 1.25, 1.25) })),
    WoodDark: baked(new THREE.MeshPhysicalMaterial({ ...woodLook, color: new THREE.Color(0.25, 0.25, 0.25) })),
    ChartPaper: baked(new THREE.MeshStandardMaterial({ map: chart, roughness: 0.82 }), true),
    DialFace: baked(new THREE.MeshPhysicalMaterial({ map: dial, roughness: 0.55, specularIntensity: 0.6 }), true),
    Ink: baked(new THREE.MeshStandardMaterial({ color: linear(0.03, 0.025, 0.2), roughness: 0.3 })),
    Brass: metal(linear(0.8, 0.53, 0.17), 0.16),
    BrassPolished: metal(linear(0.82, 0.56, 0.19), 0.045),
    Nickel: metal(linear(0.72, 0.7, 0.66), 0.2),
    Steel: metal(linear(0.62, 0.63, 0.65), 0.14),
    BluedSteel: metal(linear(0.035, 0.05, 0.13), 0.22),
    Glass: new THREE.MeshPhysicalMaterial({
      color: linear(0.93, 0.97, 0.95),
      roughness: 0,
      metalness: 0,
      transmission: 1,
      ior: 1.5,
      thickness: 0.012,
    }),
    // The table is finished in the bake: cloth, pool of light and shadows.
    Felt: new THREE.MeshBasicMaterial({ map: cloth }),
  };

  const model = gltf.scene;
  model.traverse((node) => {
    const mesh = node as THREE.Mesh;
    if (!mesh.isMesh) return;
    const name = (mesh.material as THREE.Material).name;
    mesh.material = materials[name] ?? mesh.material;
    if (name === "Glass") mesh.layers.set(GLASS_LAYER);
  });
  scene.add(model);

  // What the metal inside the case reflects: the studio, but also the drum, the
  // dial and the woodwork around it. One look around from the middle of the case.
  const studio = makeStudioBackdrop(env);
  scene.add(studio);
  const surroundings = new THREE.WebGLCubeRenderTarget(512, { type: THREE.HalfFloatType });
  const probe = new THREE.CubeCamera(0.005, 20, surroundings);
  probe.position.copy(CASE_CENTRE);
  probe.layers.enable(STUDIO_LAYER);
  probe.update(renderer, scene);
  const pmrem = new THREE.PMREMGenerator(renderer);
  const interior = pmrem.fromCubemap(surroundings.texture);
  pmrem.dispose();
  for (const name of ["Brass", "BrassPolished", "Nickel", "Steel", "BluedSteel"]) {
    (materials[name] as THREE.MeshStandardMaterial).envMap = interior.texture;
  }

  // The bed plate is a true mirror.
  const mirror = new Reflector(new THREE.PlaneGeometry(BED_PLATE.x, BED_PLATE.z), {
    textureWidth: 2048,
    textureHeight: 1024,
    color: linear(0.82, 0.56, 0.19),
    shader: BRASS_MIRROR,
  });
  mirror.rotateX(-Math.PI / 2);
  mirror.position.set(0, BED_PLATE.y, 0);
  scene.add(mirror);

  // Frame it as the Blender camera does.
  const source = gltf.cameras[0] as THREE.PerspectiveCamera;
  model.updateMatrixWorld(true);
  const designFov = THREE.MathUtils.degToRad(source.fov);
  const camera = new THREE.PerspectiveCamera(source.fov, DESIGN_ASPECT, 0.05, 30);
  source.getWorldPosition(camera.position);
  camera.lookAt(TARGET);
  camera.layers.enable(GLASS_LAYER);
  // The mirror's eye sees the studio but not the glass.
  const mirrorEye = (mirror as unknown as { getReflectionCamera(c: THREE.Camera): THREE.Camera }).getReflectionCamera(camera);
  mirrorEye.layers.set(0);
  mirrorEye.layers.enable(STUDIO_LAYER);

  const controls = new OrbitControls(camera, canvas);
  controls.target.copy(TARGET);
  controls.enablePan = false;
  controls.enableDamping = true;
  controls.minDistance = 0.9;
  controls.maxDistance = 2.6;
  controls.minPolarAngle = THREE.MathUtils.degToRad(50);
  controls.maxPolarAngle = THREE.MathUtils.degToRad(88);
  controls.minAzimuthAngle = THREE.MathUtils.degToRad(-70);
  controls.maxAzimuthAngle = THREE.MathUtils.degToRad(70);

  const penArm = model.getObjectByName("PenArm");
  const needle = model.getObjectByName("Needle");

  let dirty = true;
  const invalidate = () => {
    dirty = true;
  };
  controls.addEventListener("change", invalidate);

  const holder = canvas.parentElement ?? canvas;
  const fit = () => {
    const w = Math.max(1, holder.clientWidth);
    const h = Math.max(1, holder.clientHeight);
    renderer.setSize(w, h, false);
    view.setSize(Math.round(w * drawScale()), Math.round(h * drawScale()));
    camera.aspect = w / h;
    // Narrower than the design frame: widen the view so the instrument still fits.
    const half = Math.tan(designFov / 2) * Math.max(1, DESIGN_ASPECT / camera.aspect);
    camera.fov = THREE.MathUtils.radToDeg(2 * Math.atan(half));
    camera.updateProjectionMatrix();
    invalidate();
  };
  const observer = new ResizeObserver(fit);
  observer.observe(holder);
  fit();

  let frame = 0;
  const tick = () => {
    frame = requestAnimationFrame(tick);
    controls.update();
    if (!dirty) return;
    dirty = false;
    draw();
  };
  tick();

  if (import.meta.env.DEV) {
    // For poking at the scene from the dev tools, and for posting a frame to
    // Dashboard/Barograph/model/dev_shot_sink.py to compare with a Blender render.
    const capture = async (name: string, width = 1920, height = 1080, sink = "http://localhost:8765") => {
      renderer.setPixelRatio(1);
      renderer.setSize(width, height, false);
      view.setSize(Math.round(width * SUPERSAMPLE), Math.round(height * SUPERSAMPLE));
      camera.aspect = width / height;
      camera.fov = THREE.MathUtils.radToDeg(designFov);
      camera.updateProjectionMatrix();
      draw();
      // toDataURL, not toBlob: it is synchronous, so it works in a background tab.
      const png = atob(canvas.toDataURL("image/png").split(",")[1]);
      const bytes = new Uint8Array(png.length);
      for (let i = 0; i < png.length; i++) bytes[i] = png.charCodeAt(i);
      const reply = await fetch(`${sink}/${name}`, { method: "POST", body: bytes });
      return reply.text();
    };
    Object.assign(window, {
      barographDebug: { THREE, renderer, scene, camera, controls, materials, model, mirror, view, draw, invalidate, capture },
    });
  }

  return {
    setPressure(inHg: number) {
      const rise = ((inHg - 29.5) / 3) * CHART_GRID_M;
      const swing = Math.asin(THREE.MathUtils.clamp(rise / PEN_ARM_M, -0.3, 0.3));
      penArm?.quaternion.setFromAxisAngle(ARM_AXIS, swing);
      needle?.quaternion.setFromAxisAngle(UP, -(inHg - 29.5) * DIAL_RAD_PER_INHG);
      invalidate();
    },
    dispose() {
      cancelAnimationFrame(frame);
      observer.disconnect();
      controls.dispose();
      scene.traverse((node) => {
        const mesh = node as THREE.Mesh;
        if (mesh.isMesh) mesh.geometry.dispose();
      });
      for (const m of Object.values(materials)) m.dispose();
      for (const t of [env, lut, woodDiff, woodNormal, dial, chart, light, occlusion, cloth]) t.dispose();
      view.dispose();
      surroundings.dispose();
      interior.dispose();
      mirror.dispose();
      (studio.material as THREE.Material).dispose();
      renderer.dispose();
      renderer.forceContextLoss(); // free the GPU context now, not when the page is collected
    },
  };
}
