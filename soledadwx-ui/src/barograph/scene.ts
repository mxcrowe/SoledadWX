// The barograph, drawn live with three.js.
//
// The model, its lighting and its textures come from Dashboard/Barograph/model
// (export_web.py writes public/barograph/). Blender works out the soft,
// shadowed, bounced light once and bakes it; this file adds what has to be
// live: reflections that follow the eye, and the moving parts.
//
// Names it relies on in the model: Drum, ChartClip, PenArbor, PenArm, CrankPin,
// TopLever, LeverPin, StackPin, Link, StackPost, PenLifter, PaperLever,
// Quadrant*, Needle. Materials are matched by name.

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { HDRLoader } from "three/addons/loaders/HDRLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { Reflector } from "three/addons/objects/Reflector.js";
import { createViewTransform } from "./tonemap";
import { WEEK_HOURS } from "./chart";

const ASSETS = `${import.meta.env.BASE_URL}barograph/`;

// Shared with build_barograph.py (millimetres there, metres here).
const PEN_ARM_M = 0.173;
const CHART_GRID_M = 0.09; // the height of the chart's grid, bottom of the scale to top
const CHART_AT_PEN_HOURS = 82; // the hour of the week under the pen in the model as built
const PEN_LIFT_RAD = THREE.MathUtils.degToRad(4); // how far the lifter swings the pen off the paper
const LIFTER_SWING_RAD = THREE.MathUtils.degToRad(31); // the turn of the lifter's foot that brings its rod that far
// The dial thermometer, as in make_textures.py and build_barograph.py: where
// 0 and 140 degrees F fall (clockwise from the top of the dial), the tube's
// sweep from its bulb (anticlockwise from the dial's right), and its colours.
const THERMO = { f0: 236, f140: 124, from: -150, to: -30 };
const THERMO_WHITE = [0.8, 0.78, 0.7] as const;
const THERMO_RED = [0.45, 0.012, 0.02] as const;
// Across the tube, back (against the dial) to front: where each band starts,
// and its colour with the spirit in it and without (THERMO_BANDS in the build).
const THERMO_BANDS: [number, readonly number[], readonly number[]][] = [
  [0.0, [0.8, 0.78, 0.7], [0.8, 0.78, 0.7]], // the dial seen through the glass
  [0.5, [0.55, 0.55, 0.52], [0.55, 0.55, 0.52]], // the glass wall, seen edge on
  [0.7, [0.88, 0.88, 0.85], [0.88, 0.88, 0.85]], // clear glass over the dial
  [0.89, [0.8, 0.3, 0.28], [0.88, 0.88, 0.85]], // the spirit, lit through its edge
  [0.935, THERMO_RED, [0.88, 0.88, 0.85]], // the spirit: the middle half of the tube
];
const ROOM_F = 68; // shown until a reading arrives
// The paper selector: the lever's turn at each of its three positions (BAR,
// THERM, HYGR), as built in build_barograph.py, and how fast it swings there.
const SELECTOR_RAD = [50, 0, -50].map(THREE.MathUtils.degToRad);
const SELECTOR_STEP_RAD = THREE.MathUtils.degToRad(5);
const PAPER_RADIUS_M = 0.0466;
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

/**
 * The movement between the stack and the pen. The crank on the pen arbor pulls
 * a link of fixed length, the link turns the top lever, and the lever's short
 * end presses on the stack. build_barograph.py poses its stills by the same
 * rule (lever_angle). Returns null if the model has no movement.
 */
function makeMovement(model: THREE.Object3D): ((swing: number) => void) | null {
  const parts = ["PenArbor", "CrankPin", "TopLever", "LeverPin", "StackPin", "Link", "StackPost"].map((name) =>
    model.getObjectByName(name),
  );
  if (parts.some((part) => !part)) return null;
  const [penArbor, crankPin, lever, leverPin, stackPin, link, post] = parts as THREE.Object3D[];

  model.updateMatrixWorld(true);
  const a = leverPin.getWorldPosition(new THREE.Vector3());
  const linkLength = a.distanceTo(crankPin.getWorldPosition(new THREE.Vector3()));
  // The post stands on the stack and hangs from the lever's short end.
  const postBelowPin = post.position.y - stackPin.getWorldPosition(a).y;
  const reach = Math.hypot(leverPin.position.x, leverPin.position.y);
  const leverRest = Math.atan2(leverPin.position.y, leverPin.position.x);

  // In the plane the arbors turn in, x runs across and y up, and a turn about
  // ARM_AXIS takes (x, y) to (x cos + y sin, y cos - x sin).
  const turned = (v: THREE.Vector3, angle: number): [number, number] => [
    v.x * Math.cos(angle) + v.y * Math.sin(angle),
    v.y * Math.cos(angle) - v.x * Math.sin(angle),
  ];

  return (swing) => {
    const [cx, cy] = turned(crankPin.position, swing);
    const crankX = penArbor.position.x + cx;
    const crankY = penArbor.position.y + cy;
    const vx = crankX - lever.position.x;
    const vy = crankY - lever.position.y;
    const span = Math.hypot(vx, vy);
    const cos = (reach * reach + span * span - linkLength * linkLength) / (2 * reach * span);
    const spread = Math.acos(THREE.MathUtils.clamp(cos, -1, 1));
    const base = leverRest - Math.atan2(vy, vx);
    const leverTurn = Math.abs(base - spread) < Math.abs(base + spread) ? base - spread : base + spread;
    lever.quaternion.setFromAxisAngle(ARM_AXIS, leverTurn);

    const [lx, ly] = turned(leverPin.position, leverTurn);
    link.position.x = lever.position.x + lx;
    link.position.y = lever.position.y + ly;
    // The link hangs down its own -Y from the lever's pin to the crank's.
    link.quaternion.setFromAxisAngle(ARM_AXIS, Math.atan2(link.position.x - crankX, link.position.y - crankY));
    post.position.y = lever.position.y + turned(stackPin.position, leverTurn)[1] + postBelowPin;
  };
}

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
// The chart paper is sharp print too, and can show a second sheet over part of
// its length: the new paper, wrapping on behind the clip while the drum turns.
const PAPER_PRINT = THREE.ShaderChunk.map_fragment.replace(
  "texture2D( map, vMapUv )",
  "( vPaperU < wrapSplit ? texture2D( nextMap, vMapUv, -0.8 ) : texture2D( map, vMapUv, -0.8 ) )",
);
// Draw at more than the screen's resolution and scale down: it steadies thin
// lines, bevel glints and reflections.
const SUPERSAMPLE = 1.5;

export interface BarographOptions {
  /** The chart paper's texture, one week round the drum (chart.ts). */
  chart: THREE.Texture;
  /** The drum was dragged; positive hours turn it forward in time. */
  onDrumDrag?(hours: number): void;
  /** The drag on the drum ended. */
  onDrumRelease?(): void;
  /** The paper selector was worked: the position asked for (0, 1 or 2). */
  onSelect?(position: number): void;
}

export interface Barograph {
  /** Pose the pen, and the movement behind it, at a height up the chart's grid: 0 at the bottom, 1 at the top. */
  setPen(fraction: number): void;
  /** Point the dial's needle at a sea-level pressure in inHg. */
  setNeedle(inHg: number): void;
  /** The colour of the ink in the pen (a CSS colour). */
  setInk(colour: string): void;
  /** A second sheet to wrap onto the drum over the chart (see setWrap), or null to take it away. */
  setIncoming(sheet: THREE.Texture | null): void;
  /** How much of the paper's length, from the clip on, shows the incoming sheet: 0 to 1. */
  setWrap(split: number): void;
  /** Swing the paper selector's lever to a position (0, 1 or 2). */
  setSelector(position: number): void;
  /** Set the dial thermometer's spirit column, in degrees Fahrenheit. */
  setTemperature(degF: number): void;
  /** Turn the drum so this hour of the week (0 = Monday 00:00) is under the pen. Hours outside the week turn it on. */
  setPenTime(hoursIntoWeek: number): void;
  /** Lift the pen off the paper (true) or let it down (false). It swings there gently. */
  setPenLifted(lifted: boolean): void;
  /** Redraw: call after changing the chart texture. */
  invalidate(): void;
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

export async function createBarograph(canvas: HTMLCanvasElement, options: BarographOptions): Promise<Barograph> {
  const chart = options.chart;
  // The scene is drawn in scene-linear light; `view` turns that into display colours.
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  const drawScale = () => Math.min(renderer.getPixelRatio() * SUPERSAMPLE, 3);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0, 0, 0);

  const textures = new THREE.TextureLoader();
  const aniso = renderer.capabilities.getMaxAnisotropy();
  const [gltf, env, lut, woodDiff, woodNormal, dial, light, occlusion, cloth] = await Promise.all([
    new GLTFLoader().loadAsync(ASSETS + "barograph.glb"),
    new HDRLoader().loadAsync(ASSETS + "studio_env.hdr"),
    textures.loadAsync(ASSETS + "view_lut.png"),
    loadTexture(textures, "wood_diff.jpg", true, aniso),
    loadTexture(textures, "wood_normal.jpg", false, aniso),
    loadTexture(textures, "dial.png", true, aniso),
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

  // The thermometer, painted to look like glass (it cannot be clear: it would
  // vanish behind the case's panes). Left column: with spirit; right: empty.
  // Rows run across the tube, and the left half is slid along it.
  const ROWS = 64;
  const strip = new Uint8Array(2 * ROWS * 4);
  const bandColour = (v: number, which: 1 | 2) => {
    let k = 0;
    while (k + 1 < THERMO_BANDS.length && THERMO_BANDS[k + 1][0] <= v) k++;
    const v0 = THERMO_BANDS[k][0];
    const c0 = THERMO_BANDS[k][which];
    if (k + 1 === THERMO_BANDS.length) return c0;
    const v1 = THERMO_BANDS[k + 1][0];
    const c1 = THERMO_BANDS[k + 1][which];
    const f = (v - v0) / (v1 - v0);
    return c0.map((c, i) => c + (c1[i] - c) * f);
  };
  for (let row = 0; row < ROWS; row++) {
    const v = 1 - (row + 0.5) / ROWS; // glTF flips V: row 0 is the front of the tube
    ([1, 2] as const).forEach((which, col) => {
      const [r, g, b] = bandColour(v, which);
      const c = linear(r, g, b).convertLinearToSRGB();
      strip.set([Math.round(c.r * 255), Math.round(c.g * 255), Math.round(c.b * 255), 255], (row * 2 + col) * 4);
    });
  }
  const column = new THREE.DataTexture(strip, 2, ROWS, THREE.RGBAFormat);
  column.colorSpace = THREE.SRGBColorSpace;
  column.magFilter = column.minFilter = THREE.NearestFilter;
  column.repeat.x = 0.5;
  column.needsUpdate = true;
  const showTemperature = (degF: number) => {
    const deg = 90 - (THERMO.f0 + ((THERMO.f140 - THERMO.f0) * degF) / 140);
    const level = THREE.MathUtils.clamp((deg - THERMO.from) / (THERMO.to - THERMO.from), 0.01, 1);
    column.offset.x = 0.5 - 0.5 * level; // the red half covers the tube up to `level` of its length
  };
  showTemperature(ROOM_F);

  // The sheet wrapping onto the drum during a change of paper, and how far it has got.
  const wrap = { nextMap: { value: chart as THREE.Texture }, wrapSplit: { value: 0 } };

  /** A surface whose diffuse light comes from the bake. `look` says how its texture is read. */
  const baked = <T extends THREE.MeshStandardMaterial>(material: T, look: "plain" | "print" | "paper" = "plain"): T => {
    material.lightMap = light;
    material.lightMapIntensity = Math.PI * LIGHT_SCALE;
    material.aoMap = occlusion;
    material.onBeforeCompile = (shader) => {
      shader.fragmentShader = shader.fragmentShader
        .replace("#include <lights_fragment_maps>", LIGHTS_WITHOUT_STUDIO_DIFFUSE)
        .replace("#include <aomap_fragment>", OCCLUDE_REFLECTIONS_ONLY);
      if (look === "print") shader.fragmentShader = shader.fragmentShader.replace("#include <map_fragment>", SHARP_PRINT);
      if (look === "paper") {
        Object.assign(shader.uniforms, wrap);
        // U runs once round the drum from the clip, before the chart is scrolled.
        shader.vertexShader = shader.vertexShader
          .replace("#include <common>", "#include <common>\nvarying float vPaperU;")
          .replace("#include <uv_vertex>", "#include <uv_vertex>\n\tvPaperU = uv.x;");
        shader.fragmentShader = shader.fragmentShader
          .replace(
            "#include <common>",
            "#include <common>\nuniform sampler2D nextMap;\nuniform float wrapSplit;\nvarying float vPaperU;",
          )
          .replace("#include <map_fragment>", PAPER_PRINT);
      }
    };
    material.customProgramCacheKey = () => `baked-${look}`;
    return material;
  };
  // Metal in a crevice mirrors its bright neighbours, so occlusion dims it only a little.
  // Satin metal mirrors less sharply, so it is dimmed more.
  const metal = (colour: THREE.Color, roughness: number, occluded = 0.3) =>
    new THREE.MeshStandardMaterial({ color: colour, metalness: 1, roughness, aoMap: occlusion, aoMapIntensity: occluded });
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
    ChartPaper: baked(new THREE.MeshStandardMaterial({ map: chart, roughness: 0.82 }), "paper"),
    DialFace: baked(new THREE.MeshPhysicalMaterial({ map: dial, roughness: 0.55, specularIntensity: 0.6 }), "print"),
    Ink: baked(new THREE.MeshStandardMaterial({ color: linear(0.03, 0.025, 0.2), roughness: 0.3 })),
    Engraving: baked(new THREE.MeshStandardMaterial({ color: linear(0.015, 0.012, 0.01), roughness: 0.7 })),
    Ebonite: baked(new THREE.MeshStandardMaterial({ color: linear(0.012, 0.012, 0.014), roughness: 0.25 })),
    // Clear glass cannot be drawn inside the case (it would vanish behind the
    // panes), so the ink bottle is full and the thermometer tube is enamel-backed.
    InkGlass: baked(new THREE.MeshStandardMaterial({ color: linear(0.012, 0.012, 0.035), roughness: 0.03 })),
    ThermoGlass: baked(new THREE.MeshStandardMaterial({ color: linear(...THERMO_WHITE), roughness: 0.08 })),
    ThermoSpirit: baked(
      new THREE.MeshPhysicalMaterial({ color: linear(...THERMO_RED), roughness: 0.06, clearcoat: 1, clearcoatRoughness: 0.03 }),
    ),
    ThermoTube: baked(
      new THREE.MeshPhysicalMaterial({ map: column, roughness: 0.15, clearcoat: 1, clearcoatRoughness: 0.03 }),
    ),
    Brass: metal(linear(0.8, 0.53, 0.17), 0.16),
    BrassSatin: metal(linear(0.8, 0.55, 0.2), 0.3, 0.7),
    BlackSteel: metal(linear(0.09, 0.09, 0.1), 0.34),
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
  for (const name of ["Brass", "BrassPolished", "BrassSatin", "Nickel", "Steel", "BluedSteel", "BlackSteel"]) {
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
  controls.minPolarAngle = THREE.MathUtils.degToRad(10); // nearly overhead, to look down through the top glass
  controls.maxPolarAngle = THREE.MathUtils.degToRad(88);
  // Far enough round each side to face the ends: the paper selector is read from the right.
  controls.minAzimuthAngle = THREE.MathUtils.degToRad(-120);
  controls.maxAzimuthAngle = THREE.MathUtils.degToRad(120);

  // The pen arbor swings with the pressure and takes the movement with it. The
  // pen arm, inside it, is pushed off the paper by the lifter's rod.
  const penArbor = model.getObjectByName("PenArbor");
  const penArm = model.getObjectByName("PenArm");
  const lifter = model.getObjectByName("PenLifter");
  const needle = model.getObjectByName("Needle");
  const drum = model.getObjectByName("Drum");
  const clip = model.getObjectByName("ChartClip");
  const lever = model.getObjectByName("PaperLever");
  const poseMovement = makeMovement(model);
  let selected = 0;
  let leverTurn = SELECTOR_RAD[0];
  let penSwing = 0;
  let lift = 0;
  let liftTarget = 0;
  const poseArm = () => {
    penArbor?.quaternion.setFromAxisAngle(ARM_AXIS, penSwing);
    penArm?.quaternion.setFromAxisAngle(UP, lift * PEN_LIFT_RAD);
    lifter?.quaternion.setFromAxisAngle(UP, lift * LIFTER_SWING_RAD);
    poseMovement?.(penSwing);
  };

  let dirty = true;
  const invalidate = () => {
    dirty = true;
  };
  controls.addEventListener("change", invalidate);

  const holder = canvas.parentElement ?? canvas;

  // Dragging the drum turns it; dragging anywhere else looks around. This
  // listener sees the press first (capture, on the canvas's parent), and keeps
  // it from the orbit controls when it lands on the drum.
  const ray = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  const pivot = new THREE.Vector3();
  /** What is under the pointer: the drum, a position on the paper selector, or nothing that answers. */
  const partAt = (event: PointerEvent): "drum" | { select: number } | null => {
    const box = canvas.getBoundingClientRect();
    pointer.set(((event.clientX - box.left) / box.width) * 2 - 1, -((event.clientY - box.top) / box.height) * 2 + 1);
    ray.setFromCamera(pointer, camera);
    const hit = ray.intersectObject(model, true).find((h) => (h.object as THREE.Mesh).material !== materials.Glass);
    for (let node: THREE.Object3D | null = hit?.object ?? null; node; node = node.parent) {
      if (node === drum) return "drum";
      // The lever itself steps on to the next paper.
      if (node === lever) return { select: (selected + 1) % SELECTOR_RAD.length };
      if (lever && node.name.startsWith("Quadrant")) {
        // A place on the quadrant asks for the position nearest it. Seen from
        // above, the lever at no turn points along -X from its pivot.
        lever.getWorldPosition(pivot);
        const turn = Math.atan2(hit!.point.z - pivot.z, pivot.x - hit!.point.x);
        const gaps = SELECTOR_RAD.map((at) => Math.abs(at - turn));
        return { select: gaps.indexOf(Math.min(...gaps)) };
      }
    }
    return null;
  };
  /** Screen pixels per hour of paper at the front of the drum. */
  const pixelsPerHour = (): number => {
    const centre = new THREE.Vector3();
    drum!.getWorldPosition(centre);
    centre.y = 0.17;
    const right = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion).multiplyScalar(PAPER_RADIUS_M);
    const a = centre.clone().sub(right).project(camera);
    const b = centre.clone().add(right).project(camera);
    const diameterPx = (Math.abs(b.x - a.x) / 2) * canvas.getBoundingClientRect().width;
    return Math.max(0.1, (diameterPx * Math.PI) / WEEK_HOURS);
  };
  let dragX: number | null = null;
  let perHour = 1;
  let pressed: { select: number; x: number; y: number } | null = null;
  const press = (event: PointerEvent) => {
    if (event.button !== 0) return;
    const part = partAt(event);
    if (!part) return;
    if (part !== "drum") {
      // A click on the selector works it; a drag that starts there still looks around.
      pressed = { select: part.select, x: event.clientX, y: event.clientY };
      return;
    }
    event.stopPropagation();
    dragX = event.clientX;
    perHour = pixelsPerHour();
    canvas.setPointerCapture(event.pointerId);
    canvas.style.cursor = "ew-resize";
  };
  const move = (event: PointerEvent) => {
    if (dragX === null) {
      if (event.buttons === 0) {
        const part = partAt(event);
        canvas.style.cursor = part === "drum" ? "ew-resize" : part ? "pointer" : "";
      }
      return;
    }
    // Dragging the paper to the right brings earlier hours to the pen.
    const hours = -(event.clientX - dragX) / perHour;
    dragX = event.clientX;
    if (hours !== 0) options.onDrumDrag?.(hours);
  };
  const release = (event: PointerEvent) => {
    if (pressed) {
      if (Math.hypot(event.clientX - pressed.x, event.clientY - pressed.y) < 5) options.onSelect?.(pressed.select);
      pressed = null;
    }
    if (dragX === null) return;
    dragX = null;
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    options.onDrumRelease?.();
  };
  holder.addEventListener("pointerdown", press, { capture: true });
  canvas.addEventListener("pointermove", move);
  canvas.addEventListener("pointerup", release);
  canvas.addEventListener("pointercancel", release);
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
    if (lift !== liftTarget) {
      const step = 0.06;
      lift = Math.abs(liftTarget - lift) <= step ? liftTarget : lift + Math.sign(liftTarget - lift) * step;
      poseArm();
      dirty = true;
    }
    const leverGap = SELECTOR_RAD[selected] - leverTurn;
    if (leverGap !== 0 && lever) {
      leverTurn = Math.abs(leverGap) <= SELECTOR_STEP_RAD ? SELECTOR_RAD[selected] : leverTurn + Math.sign(leverGap) * SELECTOR_STEP_RAD;
      lever.rotation.y = leverTurn;
      dirty = true;
    }
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
    setPen(fraction: number) {
      // The pen stops at the edges of the chart, as on the real instrument.
      const rise = (THREE.MathUtils.clamp(fraction, 0, 1) - 0.5) * CHART_GRID_M;
      penSwing = Math.asin(rise / PEN_ARM_M);
      poseArm();
      invalidate();
    },
    setNeedle(inHg: number) {
      // The dial has its own scale, 28 to 31 inHg, with 29.5 straight up.
      needle?.quaternion.setFromAxisAngle(UP, -(inHg - 29.5) * DIAL_RAD_PER_INHG);
      invalidate();
    },
    setInk(colour: string) {
      (materials.Ink as THREE.MeshStandardMaterial).color.set(colour);
      invalidate();
    },
    setIncoming(sheet: THREE.Texture | null) {
      wrap.nextMap.value = sheet ?? chart;
      if (!sheet) wrap.wrapSplit.value = 0;
      invalidate();
    },
    setWrap(split: number) {
      wrap.wrapSplit.value = split;
      invalidate();
    },
    setSelector(position: number) {
      selected = THREE.MathUtils.clamp(Math.round(position), 0, SELECTOR_RAD.length - 1);
      invalidate();
    },
    setTemperature(degF: number) {
      showTemperature(degF);
      invalidate();
    },
    setPenTime(hoursIntoWeek: number) {
      const turns = (hoursIntoWeek - CHART_AT_PEN_HOURS) / WEEK_HOURS;
      chart.offset.x = turns;
      // The clip that holds the chart's ends goes round with the paper.
      if (clip) clip.rotation.y = -turns * 2 * Math.PI;
      invalidate();
    },
    setPenLifted(lifted: boolean) {
      liftTarget = lifted ? 1 : 0;
    },
    invalidate,
    dispose() {
      cancelAnimationFrame(frame);
      observer.disconnect();
      controls.dispose();
      holder.removeEventListener("pointerdown", press, { capture: true });
      canvas.removeEventListener("pointermove", move);
      canvas.removeEventListener("pointerup", release);
      canvas.removeEventListener("pointercancel", release);
      scene.traverse((node) => {
        const mesh = node as THREE.Mesh;
        if (mesh.isMesh) mesh.geometry.dispose();
      });
      for (const m of Object.values(materials)) m.dispose();
      for (const t of [env, lut, woodDiff, woodNormal, dial, light, occlusion, cloth, column]) t.dispose();
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
