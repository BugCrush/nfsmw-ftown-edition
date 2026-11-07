// Exports one car's collections from a Most Wanted packed file (GlobalB.lzc) with Nikki, the library Binarius uses,
// in the serialized form Binarius's `import` reads. Read-only on the input.
// Usage: NikkiExport <GlobalB.lzc> <out dir> <collection> <manager> [<manager> ...]
// Writes <out dir>\<manager>.bin for each manager; exit code 2 if a manager or the collection is missing.
using System;
using System.IO;

static class NikkiExport
{
    static int Main(string[] args)
    {
        if (args.Length < 4)
        {
            Console.Error.WriteLine("usage: NikkiExport <GlobalB.lzc> <out dir> <collection> <manager> [<manager> ...]");
            return 1;
        }
        var db = new Nikki.Support.MostWanted.Datamap();
        db.Load(new Nikki.Core.Options { File = args[0] });
        Directory.CreateDirectory(args[1]);
        for (int i = 3; i < args.Length; i++)
        {
            var manager = db.GetManager(args[i]);
            if (manager == null)
            {
                Console.Error.WriteLine("no manager " + args[i]);
                return 2;
            }
            string name = args[2];
            // a collection whose name Nikki could not look up is named by its hash ("0x3C21C0BC" for CHALLENGER71)
            // (or, for collisions, which are keyed by the database hash, "0x3A3A461D")
            if (manager.FindIndex(name) < 0)
                name = "0x" + Nikki.Utils.Hashing.BinHash(args[2]).ToString("X8");
            if (manager.FindIndex(name) < 0)
                name = "0x" + Nikki.Utils.Hashing.VltHash(args[2]).ToString("X8");
            if (manager.FindIndex(name) < 0)
            {
                Console.Error.WriteLine("no collection " + args[2] + " in " + args[i] + "; its last ones:");
                for (int k = Math.Max(0, manager.Count - 5); k < manager.Count; k++)
                    Console.Error.WriteLine("  " + ((Nikki.Reflection.Abstract.Collectable)manager[k]).CollectionName);
                return 2;
            }
            using var bw = new BinaryWriter(File.Create(Path.Combine(args[1], args[i] + ".bin")));
            db.Export(args[i], name, bw, true);
            Console.WriteLine("exported " + args[i] + " " + name);
        }
        return 0;
    }
}
