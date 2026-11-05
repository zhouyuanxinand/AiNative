/** Authored ellipsoids in model space: +Y is up, +Z is the front of the suit. */
interface Transform { center: number[]; radii: number[]; rot?: number[] }
interface PilotPart extends Transform { name: string; color: string }
export interface PilotModel {
  parts: PilotPart[];
  poses: Record<string, Partial<Transform>>[];
  camera?: {yawDegrees:number; pitchDegrees:number; projectedBottom:number; unitsPerPixel:number; anchor:number[]};
}

const radians = Math.PI / 180;
const vertex = `
precision highp float;
precision highp int;
attribute vec3 sphere;
attribute vec3 center, radii, color;
attribute mat3 rotation;
uniform mat3 camera, lamp;
uniform vec3 framing;
uniform bool shadowPass;
varying vec3 normal, tint, shadowCoord;
void main() {
  vec3 p = rotation * (sphere * radii) + center;
  normal = rotation * (sphere / radii);
  tint = color;
  vec3 lightSpace = lamp * (p - vec3(0., 1.375, 0.));
  vec3 shadowClip = lightSpace * vec3(.57, .57, -.30);
  shadowCoord = shadowClip * .5 + .5;
  vec3 eye = camera * p;
  // The original sprite is 124 design pixels, feet at 119, with 112px for a 2.75-high pilot.
  vec3 clip = vec3(eye.xy * framing.x + framing.yz, -.22 * eye.z);
  gl_Position = vec4(shadowPass ? shadowClip : clip, 1.);
}`;
const fragment = `
precision highp float;
precision highp int;
uniform bool shadowPass;
uniform mat3 camera;
uniform sampler2D shadowMap;
varying vec3 normal, tint, shadowCoord;
void main() {
  if (shadowPass) {
    gl_FragColor = vec4(vec3(gl_FragCoord.z), 1.);
    return;
  }
  vec3 N = normalize(normal);
  vec3 L = normalize(vec3(-.55,.76,.66));
  vec3 V = vec3(camera[0].z, camera[1].z, camera[2].z);
  float facing = max(dot(N, L), 0.);
  float shadow = 0.;
  for (int i=-1;i<=1;i++) for (int j=-1;j<=1;j++) {
    float depth = texture2D(shadowMap, shadowCoord.xy + vec2(float(i),float(j))/256.).r;
    shadow += step(depth + .008 + .005*(1.-facing), shadowCoord.z) / 9.;
  }
  float key = facing * (1. - .54*shadow);
  float sky = clamp(.5 + .5*N.y, 0., 1.);
  vec3 light = mix(vec3(.30,.34,.42), vec3(.58,.62,.69), sky)
             + key * vec3(.65,.61,.55);
  float spec = pow(max(dot(N, normalize(L+V)), 0.), 32.) * (1.-.7*shadow);
  float rim = pow(1.-max(dot(N,V), 0.), 3.) * sky;
  vec3 lit = pow(tint, vec3(2.2))*light + vec3(.08,.075,.07)*spec + vec3(.012,.021,.032)*rim;
  gl_FragColor = vec4(pow(clamp(lit,0.,1.),vec3(1./2.2)),1.);
}`;

/** Column-major camera basis, looking towards the origin from azimuth/elevation in degrees. */
function view(azimuth: number, elevation: number) {
  const a = azimuth*radians, e = elevation*radians;
  const c = Math.cos(a), s = Math.sin(a), ce = Math.cos(e), se = Math.sin(e);
  return new Float32Array([c,-se*s,ce*s, 0,ce,se, -s,-se*c,ce*c]);
}
function rotation(angles?: number[]) {
  const [x,y,z] = angles ?? [0,0,0];
  const a=Math.cos(x*radians), b=Math.sin(x*radians), c=Math.cos(y*radians), d=Math.sin(y*radians);
  const e=Math.cos(z*radians), f=Math.sin(z*radians);
  return new Float32Array([e*c,f*c,-d, e*d*b-f*a,f*d*b+e*a,c*b, e*d*a+f*b,f*d*a-e*b,c*a]);
}
function sphereMesh() {
  const points: number[] = [], indices: number[] = [];
  const rings=16, sides=24;
  for(let j=0;j<=rings;j++) for(let i=0;i<=sides;i++) {
    const a=Math.PI*j/rings, b=2*Math.PI*i/sides;
    points.push(Math.sin(a)*Math.cos(b), Math.cos(a), Math.sin(a)*Math.sin(b));
    if(j<rings && i<sides) {
      const k=j*(sides+1)+i, m=k+sides+1;
      indices.push(k,k+1,m, m,k+1,m+1);
    }
  }
  return {points:new Float32Array(points),indices:new Uint16Array(indices)};
}

/** One small offscreen context, shared geometry, no animation loop or DOM attachment. */
export function createPilotRenderer(onContextLost?: () => void) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 248;
  const gl = canvas.getContext('webgl', {alpha:true, antialias:true, depth:true, preserveDrawingBuffer:true});
  if (!gl) return null;
  const program=gl.createProgram(), vs=gl.createShader(gl.VERTEX_SHADER), fs=gl.createShader(gl.FRAGMENT_SHADER);
  const vertices=gl.createBuffer(), elements=gl.createBuffer(), instances=gl.createBuffer();
  const instancing=gl.getExtension('ANGLE_instanced_arrays');
  const shadows=gl.createTexture(), depth=gl.createRenderbuffer(), target=gl.createFramebuffer();
  let disposed=false;
  function contextLost() { dispose(); onContextLost?.(); }
  function dispose() {
    if (disposed) return;
    disposed=true;
    canvas.removeEventListener('webglcontextlost', contextLost);
    gl!.deleteFramebuffer(target); gl!.deleteRenderbuffer(depth); gl!.deleteTexture(shadows);
    gl!.deleteBuffer(vertices); gl!.deleteBuffer(elements); gl!.deleteBuffer(instances);
    gl!.deleteProgram(program); gl!.deleteShader(vs); gl!.deleteShader(fs);
    if (!gl!.isContextLost()) gl!.getExtension('WEBGL_lose_context')?.loseContext();
  }
  if (!program || !vs || !fs || !vertices || !elements || !instances || !shadows || !depth || !target) {dispose(); return null;}
  gl.shaderSource(vs,vertex); gl.compileShader(vs);
  gl.shaderSource(fs,fragment); gl.compileShader(fs);
  gl.attachShader(program,vs); gl.attachShader(program,fs); gl.linkProgram(program);
  if (!gl.getProgramParameter(program,gl.LINK_STATUS)) {dispose(); return null;}
  gl.useProgram(program);
  const uniforms=Object.fromEntries(['camera','lamp','framing','shadowPass','shadowMap']
    .map(name=>[name,gl.getUniformLocation(program,name)]));
  const mesh=sphereMesh(), attr=gl.getAttribLocation(program,'sphere');
  gl.bindBuffer(gl.ARRAY_BUFFER,vertices); gl.bufferData(gl.ARRAY_BUFFER,mesh.points,gl.STATIC_DRAW);
  gl.enableVertexAttribArray(attr); gl.vertexAttribPointer(attr,3,gl.FLOAT,false,0,0);
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,elements); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,mesh.indices,gl.STATIC_DRAW);
  const at=(name:string)=>gl.getAttribLocation(program,name);
  const rot=at('rotation'), attributes=[at('center'),at('radii'),rot,rot+1,rot+2,at('color')];
  if(instancing) {
    gl.bindBuffer(gl.ARRAY_BUFFER,instances);
    attributes.forEach((loc,i)=>{
      gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc,3,gl.FLOAT,false,18*4,i*3*4);
      instancing.vertexAttribDivisorANGLE(loc,1);
    });
  }
  gl.bindTexture(gl.TEXTURE_2D,shadows);
  gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,256,256,0,gl.RGBA,gl.UNSIGNED_BYTE,null);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.NEAREST);
  gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
  gl.bindRenderbuffer(gl.RENDERBUFFER,depth); gl.renderbufferStorage(gl.RENDERBUFFER,gl.DEPTH_COMPONENT16,256,256);
  gl.bindFramebuffer(gl.FRAMEBUFFER,target);
  gl.framebufferTexture2D(gl.FRAMEBUFFER,gl.COLOR_ATTACHMENT0,gl.TEXTURE_2D,shadows,0);
  gl.framebufferRenderbuffer(gl.FRAMEBUFFER,gl.DEPTH_ATTACHMENT,gl.RENDERBUFFER,depth);
  if(gl.checkFramebufferStatus(gl.FRAMEBUFFER)!==gl.FRAMEBUFFER_COMPLETE){dispose(); return null;}
  gl.uniformMatrix3fv(uniforms.lamp,false,view(Math.atan2(-.55,.66)/radians,Math.atan2(.76,Math.hypot(-.55,.66))/radians));
  gl.uniform1i(uniforms.shadowMap,0);
  gl.enable(gl.DEPTH_TEST); gl.enable(gl.CULL_FACE);
  canvas.addEventListener('webglcontextlost',contextLost);
  let lastModel:PilotModel|undefined, lastFrame=-1, lastYaw=NaN;
  let packed=new Float32Array(0), count=0;
  return {
    draw(model:PilotModel, frame:number, yawDegrees=model.camera?.yawDegrees??14):HTMLCanvasElement|null {
      if(disposed || gl.isContextLost()) {dispose(); return null;}
      const newPose=lastModel!==model || lastFrame!==frame;
      if (!newPose && lastYaw===yawDegrees) return canvas;
      if(newPose){
        const pose = model.poses[frame];
        packed = new Float32Array(model.parts.length*18);
        count=0;
        for(const part of model.parts) {
          const change = pose?.[part.name], rgb = parseInt(part.color.slice(1),16);
          const radii=change?.radii??part.radii;
          if(radii.some(value=>value<=0)) continue;
          const i=count++*18;
          packed.set(change?.center??part.center,i); packed.set(radii,i+3);
          packed.set(rotation(change?.rot??part.rot),i+6);
          packed.set([(rgb>>16&255)/255,(rgb>>8&255)/255,(rgb&255)/255],i+15);
        }
        if(instancing){gl.bindBuffer(gl.ARRAY_BUFFER,instances); gl.bufferData(gl.ARRAY_BUFFER,packed,gl.DYNAMIC_DRAW);}
      }
      const cam=model.camera, scale=1/((cam?.unitsPerPixel??2.75/112)*62);
      gl.uniform3f(uniforms.framing,scale,(cam?.anchor[0]??62)/62-1,1-(cam?.anchor[1]??119)/62-(cam?.projectedBottom??0)*scale);
      gl.uniformMatrix3fv(uniforms.camera,false,view(yawDegrees,cam?.pitchDegrees??4));
      for (const shadowPass of [true,false]) {
        if (shadowPass && !newPose) continue; // Light and geometry are independent of the camera.
        gl.bindTexture(gl.TEXTURE_2D,shadowPass ? null : shadows);
        gl.bindFramebuffer(gl.FRAMEBUFFER,shadowPass ? target : null);
        const size=shadowPass?256:canvas.width;
        gl.viewport(0,0,size,size);
        const bg=Number(shadowPass);
        gl.clearColor(bg,bg,bg,bg); gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
        gl.uniform1i(uniforms.shadowPass,bg);
        if(instancing) {
          instancing.drawElementsInstancedANGLE(gl.TRIANGLES,mesh.indices.length,gl.UNSIGNED_SHORT,0,count);
        } else for(let i=0;i<count;i++) {
          attributes.forEach((loc,j)=>{const k=i*18+j*3; gl.vertexAttrib3f(loc,packed[k],packed[k+1],packed[k+2]);});
          gl.drawElements(gl.TRIANGLES,mesh.indices.length,gl.UNSIGNED_SHORT,0);
        }
      }
      lastModel=model; lastFrame=frame; lastYaw=yawDegrees;
      return gl.isContextLost()?null:canvas;
    },
    dispose,
  };
}
