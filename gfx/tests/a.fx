// Effect A of the GfxProbe stand-in: one technique, one pass.
float4 g_vTint = float4(1, 0, 0, 1);
float4 VS(float4 p : POSITION) : POSITION { return p; }
float4 PS() : COLOR { return g_vTint; }
technique Main { pass P0 { VertexShader = compile vs_2_0 VS(); PixelShader = compile ps_2_0 PS(); } }
