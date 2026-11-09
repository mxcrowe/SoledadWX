// Blender's view transform, applied as a final pass.
//
// The scene is rendered to a floating-point image in scene-linear light. This
// pass turns it into display colours by looking each pixel up in a table that
// Blender's own colour management filled in (make_view_lut.py: AgX with the
// Medium High Contrast look). So the page shows what a Blender render shows,
// without re-deriving Blender's curve here.

import * as THREE from "three";

// Must agree with make_view_lut.py.
const LUT_SIZE = 48;
const LUT_LO = -12.5;
const LUT_HI = 4.5;

const VERTEX = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = vec4( position.xy, 0.0, 1.0 );
  }`;

const FRAGMENT = /* glsl */ `
  uniform sampler2D tScene;
  uniform sampler2D tLut;
  uniform float exposure;
  varying vec2 vUv;

  const float N = ${LUT_SIZE}.0;

  // One slice of the table: x = red, y = green, at a whole blue index.
  vec3 slice( vec2 rg, float blue ) {
    vec2 uv = vec2( ( blue + ( rg.x * ( N - 1.0 ) + 0.5 ) / N ) / N, ( rg.y * ( N - 1.0 ) + 0.5 ) / N );
    return texture2D( tLut, uv ).rgb;
  }

  void main() {
    vec3 light = texture2D( tScene, vUv ).rgb * exposure;
    vec3 at = clamp( ( log2( max( light, 1e-10 ) ) - ( ${LUT_LO.toFixed(1)} ) ) / ${(LUT_HI - LUT_LO).toFixed(1)}, 0.0, 1.0 );
    float blue = at.b * ( N - 1.0 );
    float below = floor( blue );
    vec3 shown = mix( slice( at.rg, below ), slice( at.rg, min( below + 1.0, N - 1.0 ) ), blue - below );
    gl_FragColor = vec4( shown, 1.0 );
    #include <colorspace_fragment>
  }`;

export interface ViewTransform {
  /** The image the scene must be rendered into. */
  readonly target: THREE.WebGLRenderTarget;
  setSize(width: number, height: number): void;
  /** Draw the target to the canvas through Blender's view transform. */
  present(renderer: THREE.WebGLRenderer): void;
  dispose(): void;
}

/** `lut` is view_lut.png, loaded as an sRGB texture. `stops` is the exposure, as in Blender. */
export function createViewTransform(lut: THREE.Texture, stops: number): ViewTransform {
  lut.colorSpace = THREE.SRGBColorSpace;
  lut.flipY = false;
  lut.generateMipmaps = false;
  lut.minFilter = lut.magFilter = THREE.LinearFilter;
  lut.wrapS = lut.wrapT = THREE.ClampToEdgeWrapping;
  lut.needsUpdate = true;

  const target = new THREE.WebGLRenderTarget(1, 1, { type: THREE.HalfFloatType, samples: 4 });
  const material = new THREE.ShaderMaterial({
    uniforms: { tScene: { value: target.texture }, tLut: { value: lut }, exposure: { value: 2 ** stops } },
    vertexShader: VERTEX,
    fragmentShader: FRAGMENT,
    depthTest: false,
    depthWrite: false,
  });
  // One triangle that covers the screen.
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute([-1, -1, 0, 3, -1, 0, -1, 3, 0], 3));
  geometry.setAttribute("uv", new THREE.Float32BufferAttribute([0, 0, 2, 0, 0, 2], 2));
  const screen = new THREE.Mesh(geometry, material);
  screen.frustumCulled = false;
  const eye = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

  return {
    target,
    setSize(width, height) {
      target.setSize(width, height);
    },
    present(renderer) {
      renderer.setRenderTarget(null);
      renderer.render(screen, eye);
    },
    dispose() {
      target.dispose();
      material.dispose();
      geometry.dispose();
    },
  };
}
