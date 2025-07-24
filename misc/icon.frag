// shadertoy

// returns a hexagonal version of "length" 
float hexagon_distance(vec2 st) {
    st = abs(st);
    float c = dot(st, vec2(0.5, 0.866));
    c = max(c, st.x);
    
    return c;
}

mat2 rotate(float angle) {
    float s = sin(angle);
    float c = cos(angle);
    
    return mat2(c, s, -s, c);
}

// period of 1
float smoothstep_square_wave(float x, float t) {
    x = fract(x);
    return smoothstep(-t, t, x) - smoothstep(0.5 - t, 0.5 + t, x) + smoothstep(1.0 - t, 1.0 + t, x);
}

const float pi = 3.14159265358;

void mainImage( out vec4 fragColor, in vec2 fragCoord )
{
    vec2 uv = (fragCoord - iResolution.xy * 0.5)/iResolution.y;
    
    uv *= rotate(-0.4);

    float angle = atan(uv.y, uv.x) + pi/6.0;
    
    float tiles = smoothstep_square_wave(angle*1.5/pi, 0.0005/length(uv));
    
    float d = hexagon_distance(uv);
    
    float aa = fwidth(d);

    float radius = 0.25;
    float rthickness = 0.08;
    
    float hex = smoothstep(radius, radius + aa, d) - smoothstep(radius + rthickness, radius + rthickness + aa, d);
    
    float col = tiles;

    col *= step(radius + rthickness * 0.5, d);
    
    //vec3 color1 = mix(vec3(0.647, 1, 0.749), vec3(0.647, 0.945, 1), uv.y + 0.5);
    //vec3 color2 = mix(vec3(0, 0.439, 0.353), vec3(0, 0.702, 0.722), uv.y + 0.5);
    vec3 color1 = vec3(0.541, 1, 0.671); // 0.525, 1, 0.776 // 0.647, 1, 0.749
    vec3 color2 = vec3(0, 0.439, 0.353);
    vec3 color3 = vec3(0.0, 0.0, 0.1);

    vec3 color = mix(color1, color2, col);
    
    color = mix(color, color3, hex);

    color += mix(vec3(0.0, 0.0, 0.0), vec3(0, 0.502, 0.4), (uv * rotate(0.05)).y + 0.3);

    // Output to screen
    fragColor = vec4(color,1.0);
}