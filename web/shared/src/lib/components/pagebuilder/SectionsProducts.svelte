<script lang="ts">
    import {onMount} from "svelte";
    import {fileConfiguration} from "$sharedLib/stores";
    import {getProducts, EVENT_KIND_AUCTION, EVENT_KIND_PRODUCT} from "$sharedLib/services/nostr";
    import {getItemsFromSection} from "$sharedLib/pagebuilder";
    import ProductCard from "$sharedLib/components/pagebuilder/ProductCard.svelte";
    import ProductCardCTA from "$sharedLib/components/pagebuilder/ProductCardCTA.svelte";

    export let pageId;
    export let sectionId;

    let products: {[productId: string]: {}} = {};
    let productsLoaded = false;

    onMount(async () => {
        let productIDs = getItemsFromSection(pageId, sectionId, 'products');

        getProducts(null, productIDs,
            (newProductInfo) => {
                // Calculate if ended
                if (newProductInfo.event.kind === EVENT_KIND_AUCTION) {
                    if (newProductInfo.start_date) {
                        let now = Math.floor(Date.now() / 1000);
                        let endsAt = newProductInfo.start_date + newProductInfo.duration;
                        newProductInfo.ended = now > endsAt;
                    } else {
                        newProductInfo.ended = false;
                    }
                }

                let productId = newProductInfo.id;
                if (!(productId in products) || (productId in products && products[productId].event.created_at < newProductInfo.event.created_at)) {
                    products[productId] = newProductInfo;
                }
            },
            () => {
                productsLoaded = true;
            });
    });
</script>

<main class="p-4 md:container mx-auto">
    {#if !productsLoaded}
        <div class="p-12 flex flex-wrap items-center justify-center">
            <span class="loading loading-bars w-24"></span>
        </div>
    {:else}
        <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3 md:gap-8 z-[300] mt-2 mb-2">
            {#each Object.entries(products) as [_, product]}
                {#if product.event.kind === EVENT_KIND_PRODUCT || (product.event.kind === EVENT_KIND_AUCTION && product.ended === false)}
                    <ProductCard {product} />
                {/if}
            {/each}

            {#if $fileConfiguration.backend_present}
                <ProductCardCTA />
            {/if}
        </div>
    {/if}
</main>
