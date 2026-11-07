// Effect B of the GfxProbe stand-in: a float the test changes, a texture it sets, an array larger than
// the 64 bytes the probe compares, and two techniques (the test draws with the second).
float g_fExposure = 0.5;
float4 g_avBig[32];
texture g_tDiffuse;
// Set to a new value every frame by the stand-in, like a per-draw setting in the game.
float4 g_vSpin;
// The array is read by the vertex shader: a 2.0 pixel shader has only 32 constant slots.
float4 VS(float4 p : POSITION) : POSITION { return p + g_avBig[31]; }
float4 PS() : COLOR { return float4(0, 0, 1, 1) * g_fExposure; }
technique Plain { pass P0 { VertexShader = compile vs_2_0 VS(); PixelShader = compile ps_2_0 PS(); } }
technique Bright { pass P0 { VertexShader = compile vs_2_0 VS(); PixelShader = compile ps_2_0 PS(); } }
